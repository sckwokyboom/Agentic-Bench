"""The rcc condition driver: the SAME prefix as phased (baseline suite →
understand → implement → suite), then either finish green or hand the red state
to the rcc loop with an RccSeed so the stitched Trace is one continuous run.
Sequential code (no langgraph needed for a linear prefix); prompt/gate helpers
are single-sourced from orchestrator.py so the phased-vs-rcc A/B shares its
prefix verbatim."""
from __future__ import annotations

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
from .rcc_mutation_graph import MutationGraph
from .regression_gate import SuiteResult
from .trace_model import Step, StepKind, Trace
from .trace_stitch import stitch


def run_rcc_condition(ocfg: OrchestratorConfig, rcfg: RccConfig,
                      sub: MutationGraph, *, phase_runner, suite_runner,
                      subset_runner, memory, strip_probes,
                      on_event=None, cancel_event=None) -> Trace:
    phase_traces: list = []
    ctrl: list = []
    clock = [0.0]
    full_runs = [0]
    productive = [0]

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

    def run_suite(phase: str) -> SuiteEval:
        full_runs[0] += 1
        try:
            return suite_runner()
        except Exception as exc:
            event(f"suite run FAILED ({exc})", phase)
            return SuiteEval(result=SuiteResult(compiled=True, ran=False,
                                                executed=0, passed=0, failed=0))

    # ── the phased-identical prefix ─────────────────────────────────────────
    base = run_suite("implement")
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
                    accepted_rounds=productive[0], reverted_rounds=0,
                    best_failed_reached=best)
        return tr

    # ── hand off the red state to the rcc loop (one continuous trace) ──────
    seed = RccSeed(phase_traces=phase_traces, ctrl=ctrl, clock=clock[0],
                   full_runs=full_runs[0], productive=productive[0],
                   best_failed=best)
    return run_rcc(rcfg, sub, cur, phase_runner=phase_runner,
                   suite_runner=suite_runner, subset_runner=subset_runner,
                   memory=memory, strip_probes=strip_probes,
                   on_event=on_event, cancel_event=cancel_event, seed=seed)
