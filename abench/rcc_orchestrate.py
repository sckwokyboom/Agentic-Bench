"""The rcc condition driver: the SAME prefix as phased (baseline suite →
understand → implement → suite), then either finish green or hand the red state
to the rcc loop with an RccSeed so the stitched Trace is one continuous run.
Sequential code (no langgraph needed for a linear prefix); prompt/gate helpers
are single-sourced from orchestrator.py so the phased-vs-rcc A/B shares its
prefix verbatim."""
from __future__ import annotations

import time

from .orchestrator import (
    _MAX_CONTRACT_CHARS,
    OrchestratorConfig,
    PhaseOutcome,
    SuiteEval,
    _cap,
    _track_best,
    contract_ok,
    fallback_contract,
    implement_prompt,
    understand_prompt,
)
from .rcc_graph import RccConfig, RccSeed, run_rcc
from .rcc_graph_layers import (
    annotate_status, build_index, build_subgraph, persist, render_prompt_slice,
    render_slice,
)
from .rcc_mutation_graph import MutationGraph
from .regression_gate import SuiteResult
from .verify import UNDERCOUNT_RATIO
from .trace_model import Step, StepKind, Trace
from .trace_stitch import stitch


def run_rcc_condition(ocfg: OrchestratorConfig, rcfg: RccConfig,
                      sub: MutationGraph, *, phase_runner, suite_runner,
                      subset_runner, memory, strip_probes,
                      full_suite_runner=None, snapshot=None, restore=None,
                      on_event=None, cancel_event=None,
                      persist_dir=None) -> Trace:
    phase_traces: list = []
    ctrl: list = []
    clock = [0.0]
    full_runs = [0]
    productive = [0]
    # Suite time/count split by WHY the controller ran it, so a cost comparison can
    # exclude harness bookkeeping the baseline arm never pays for.
    suite_time: dict[str, float] = {}
    suite_runs: dict[str, int] = {}

    def emit(payload: dict) -> None:
        if on_event is not None:
            try:
                on_event(payload)
            except Exception:
                pass

    def event(text: str, phase: str) -> None:
        clock[0] += 1.0
        emit({"type": "controller", "phase": phase, "text": text})
        ctrl.append(Step(kind=StepKind.CONTROLLER, ts=clock[0], turn=0,
                         text=text, phase=phase))

    def cancelled() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    def do_phase(name: str, prompt: str, tools: list) -> PhaseOutcome:
        if cancelled():
            event(f"run cancelled — skipping {name}", name)
            return PhaseOutcome(trace=Trace(), text="")
        emit({"type": "phase.start", "phase": name})
        emit({"type": "phase.prompt", "phase": name, "text": prompt})
        try:
            return phase_runner(name, prompt, tools)
        except Exception as exc:
            event(f"phase {name} FAILED ({exc}); continuing degraded", name)
            return PhaseOutcome(trace=Trace(), text="")

    def run_suite(phase: str, *, kind: str = "verify") -> SuiteEval:
        """Run the controller's suite, timed and attributed.

        The arm is charged for suites the AGENT never asked for, and without the
        split a cost comparison silently bills harness bookkeeping to the treatment:
        the pre-edit baseline run exists only to record a starting point, and the
        baseline arm pays nothing for it. `kind` ∈ {bookkeeping, verify}.
        """
        full_runs[0] += 1
        t0 = time.monotonic()
        try:
            return suite_runner()
        except Exception as exc:
            event(f"suite run FAILED ({exc})", phase)
            return SuiteEval(result=SuiteResult(compiled=True, ran=False,
                                                executed=0, passed=0, failed=0))
        finally:
            dt = time.monotonic() - t0
            suite_time[kind] = suite_time.get(kind, 0.0) + dt
            suite_runs[kind] = suite_runs.get(kind, 0) + 1

    # ── the phased-identical prefix ─────────────────────────────────────────
    base = run_suite("implement", kind="bookkeeping")
    best = base.result.failed if base.result.ran else None
    event(f"ran baseline test suite (stub, before any edits): "
          f"{base.result.passed} passed / {base.result.failed} failed", "implement")

    u = do_phase("understand", understand_prompt(ocfg), ["read", "grep"])
    ok, why = contract_ok(u, ocfg)
    contract = (_cap(u.text, _MAX_CONTRACT_CHARS) if ok
                else fallback_contract(base.failures, ocfg))
    event("agent's contract accepted (its spec of the method's required behaviour)"
          if ok else f"agent's contract rejected ({why}) — using an auto-derived fallback",
          "understand")
    phase_traces.append(("understand", u.trace))

    im = do_phase("implement", implement_prompt(ocfg, contract, ""), ["read", "edit"])
    cur = run_suite("implement")
    # Guard against the Gradle up-to-date undercount: after the agent ran the
    # suite itself, the controller's incremental re-run can report "0 failed"
    # over a tiny subset (executed << baseline's full count) — a FALSE green that
    # would skip rcc entirely. When the post-implement run looks green but grossly
    # under-executes vs the baseline, force ONE authoritative (--rerun-tasks) run
    # and trust THAT for the green decision. base ran on a fresh workdir, so its
    # executed count is the reliable full-suite size.
    base_exec = base.result.executed
    looks_green = cur.result.compiled and cur.result.ran and cur.result.failed == 0
    under = (base_exec and cur.result.executed is not None
             and cur.result.executed < base_exec * UNDERCOUNT_RATIO)
    if full_suite_runner is not None and looks_green and under and not cancelled():
        event(f"implement suite under-executed ({cur.result.executed} of ~{base_exec} "
              f"baseline) — forcing a full re-run before trusting green", "implement")
        full_runs[0] += 1
        try:
            cur = full_suite_runner()
        except Exception as exc:
            event(f"authoritative re-run FAILED ({exc}) — keeping incremental result",
                  "implement")
        else:
            event(f"full re-run — {cur.result.passed} passed / {cur.result.failed} "
                  f"failed (compiled={cur.result.compiled})", "implement")
    best = _track_best(cur, best, productive)
    event(f"implement done — {cur.result.passed} passed / {cur.result.failed} "
          f"failed (compiled={cur.result.compiled})", "implement")
    phase_traces.append(("implement", im.trace))

    green = cur.result.compiled and cur.result.ran and cur.result.failed == 0
    if green or cancelled():
        outcome = "cancelled" if cancelled() else "green"
        event(f"finalized: {outcome} — implement already green, rcc not invoked",
              "implement")
        tr = stitch(phase_traces, ctrl, outcome=outcome,
                    controller_test_runs=full_runs[0],
                    controller_test_time_s=sum(suite_time.values()),
                    controller_bookkeeping_runs=suite_runs.get("bookkeeping", 0),
                    controller_bookkeeping_s=suite_time.get("bookkeeping", 0.0),
                    accepted_rounds=productive[0], reverted_rounds=0,
                    best_failed_reached=best)
        return tr

    # Now that implement's red suite named the failing tests, build the R2 layers:
    # annotate the RAW graph's tests (failed/passing/unknown_reachable) — never
    # amputate it — then rank a bounded GraphSubgraph + render the v2 PromptSlice
    # (the bounded model CONTRACT) for Alpha/Gamma. render_slice (the rich
    # inspector object) is still built + persisted for debugging, but is no
    # longer what the model reads. Replaces the R1 focus() amputation (which
    # threw away the unfailing 99% of the graph before Alpha ever saw it).
    failed = {f"{f.classname}.{f.name}" for f in cur.failures}
    annotate_status(sub, failed_ids=failed)
    index = build_index(sub)
    subgraph = build_subgraph(sub, failed_ids=failed, k_methods=8)
    prompt_slice = render_prompt_slice(sub, subgraph, index)
    if persist_dir is not None:
        persist(persist_dir, sub, index, subgraph, render_slice(sub, subgraph, index),
               prompt_slice=prompt_slice)
    methods = [m["fqn"] for m in subgraph["focused_methods"]] or subgraph["methods"]
    event(f"graph layers: raw {index['method_count']}m/{index['distinct_tests']}t/"
          f"{index['chain_count']}chains → {len(methods)} focused methods, "
          f"frontier {len(subgraph['test_frontier']['failed'])} failed "
          f"+ {len(subgraph['test_frontier']['unknown_reachable_clusters'])} clusters",
          "implement")

    # ── hand off the red state to the rcc loop (one continuous trace) ──────
    seed = RccSeed(phase_traces=phase_traces, ctrl=ctrl, clock=clock[0],
                   full_runs=full_runs[0], productive=productive[0],
                   suite_s=sum(suite_time.values()),
                   bookkeeping_runs=suite_runs.get("bookkeeping", 0),
                   bookkeeping_s=suite_time.get("bookkeeping", 0.0),
                   best_failed=best)
    return run_rcc(rcfg, prompt_slice, methods, cur, phase_runner=phase_runner,
                   suite_runner=suite_runner, subset_runner=subset_runner,
                   memory=memory, strip_probes=strip_probes,
                   snapshot=snapshot, restore=restore,
                   on_event=on_event, cancel_event=cancel_event, seed=seed)
