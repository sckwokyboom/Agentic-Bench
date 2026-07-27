"""RapidCausalCoder Lite (rcc) — a LangGraph causal-debugging loop.

Single pass: memory check → [cached fast fix] → Alpha (specs) → Beta
(//[probe] println instrumentation + instrumented subset run) → strip probes →
Gamma (causal graph JSON) → CausalRank → fix top-1 → subset → full suite →
fix top-2 → DEFER. Same event/clock/stitch discipline as orchestrator_graph
(the parity-proven pattern); every dependency injected, so the whole loop runs
on fakes. Spec: docs/superpowers/specs/2026-07-08-rapidcausalcoder-mvp-design.md
"""
from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import Annotated, TypedDict

from .failure_report import cluster_failures, select_clusters
from .orchestrator import PhaseOutcome, SuiteEval, _track_best
from .rcc_prompts import (
    GAMMA_FORMAT_REMINDER, alpha_prompt, beta_prompt, beta_repair_prompt,
    cache_fix_prompt, causal_rank, fix_prompt, gamma_prompt, parse_causal_delta,
    root_rank,
)
from .regression_gate import SuiteResult
from .trace_model import Step, StepKind, Trace
from .trace_stitch import stitch


def _slice_test_classes(slice_: dict) -> list:
    """Distinct test classes reachable from the v2 PromptSlice's test frontier
    (failed_tests + each representative cluster's medoid test) — the subset-run
    scope in place of the old MutationGraph.test_classes."""
    fqns = list(slice_.get("failed_tests", []))
    for c in slice_.get("representative_path_clusters", []):
        fqns.append(c.get("medoid_test", ""))
    return sorted({fqn.rsplit(".", 1)[0] for fqn in fqns if "." in fqn})


@dataclass
class RccConfig:
    target_label: str = "the target method"
    max_attempts: int = 2          # top-1 → top-2 → DEFER
    cluster_cap: int = 5
    subset_class_cap: int = 15     # cap on test classes kept by the focus step
    revert_to_best: bool = False   # keep the best-reached worktree, not the last fix


@dataclass
class RccSeed:
    """Accumulated state from the prefix driver (baseline→understand→implement)
    so the rcc loop stitches ONE continuous trace: prior phase traces + controller
    events, the clock to continue from, and the counters so far."""
    phase_traces: list
    ctrl: list
    clock: float
    full_runs: int
    productive: int
    best_failed: "int | None"


class RccState(TypedDict, total=False):
    cached: object                 # dict | None — memory entry (fast path)
    specs: str
    probe_lines: list
    beta_ok: bool
    graph: object                  # dict | None — parsed Gamma output
    ranks: list                    # [(method_fqn, score)] desc
    root_rank: object              # int | None — CausalRank position of the target
    beta_degraded: bool
    gamma_degraded: bool
    attempt: int
    cur: SuiteEval                 # latest CLEAN suite state (never instrumented)
    best_failed: object
    best_snapshot: object          # git tree of the best-reached worktree (revert_to_best)
    outcome: object
    phase_traces: Annotated[list, operator.add]
    ctrl: Annotated[list, operator.add]


def run_rcc(cfg: RccConfig, slice_: dict, methods: list, initial: SuiteEval, *,
            phase_runner, suite_runner, subset_runner, memory, strip_probes,
            snapshot=None, restore=None,
            on_event=None, cancel_event=None, seed: "RccSeed | None" = None) -> Trace:
    """The rcc loop. `slice_` is the v2 PromptSlice (rcc_graph_layers.
    render_prompt_slice) Alpha/Beta/Gamma render; `methods` is the
    GraphSubgraph's focused-method fqn list (target first) CausalRank runs
    over. `initial` is the RED suite state that triggered rcc (the lead diff's
    failures). `subset_runner(classes) -> (SuiteEval, probe_lines)`;
    `suite_runner() -> SuiteEval` (full); `strip_probes() -> int` removes
    //[probe] lines from the working tree; `memory` is an RccMemory-like."""
    target_fqn = methods[0]
    test_classes = _slice_test_classes(slice_)
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("orchestration=rcc requires the optional dep: "
                           "pip install -e '.[langgraph]'") from exc

    clock = [seed.clock if seed else 0.0]
    full_runs = [seed.full_runs if seed else 0]
    subset_runs = [0]
    productive = [seed.productive if seed else 0]

    def emit(payload: dict) -> None:
        if on_event is not None:
            try:
                on_event(payload)
            except Exception:
                pass

    def event(text: str, phase: str) -> Step:
        clock[0] += 1.0
        emit({"type": "controller", "phase": phase, "text": text})
        return Step(kind=StepKind.CONTROLLER, ts=clock[0], turn=0, text=text,
                    phase=phase)

    def cancelled() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    def do_phase(name: str, prompt: str, tools: list, steps: list) -> PhaseOutcome:
        if cancelled():
            steps.append(event(f"run cancelled — skipping {name}", name))
            return PhaseOutcome(trace=Trace(), text="")
        emit({"type": "phase.start", "phase": name})
        emit({"type": "phase.prompt", "phase": name, "text": prompt})
        try:
            return phase_runner(name, prompt, tools)
        except Exception as exc:
            steps.append(event(f"phase {name} FAILED ({exc}); continuing degraded",
                               name))
            return PhaseOutcome(trace=Trace(), text="")

    def _norun() -> SuiteEval:
        return SuiteEval(result=SuiteResult(compiled=True, ran=False, executed=0,
                                            passed=0, failed=0))

    def run_full(steps: list, phase: str) -> SuiteEval:
        full_runs[0] += 1
        try:
            return suite_runner()
        except Exception as exc:
            steps.append(event(f"suite run FAILED ({exc})", phase))
            return _norun()

    def run_subset(steps: list, phase: str, classes: list):
        subset_runs[0] += 1
        try:
            return subset_runner(classes)
        except Exception as exc:
            steps.append(event(f"subset run FAILED ({exc})", phase))
            return _norun(), []

    def safe_strip(steps: list, phase: str) -> int:
        try:
            return strip_probes()
        except Exception as exc:
            steps.append(event(f"probe strip FAILED ({exc})", phase))
            return 0

    def snap():
        """Capture the current worktree as the best-reached state (revert_to_best
        only). No-op — returns None — when disabled or unavailable, so callers keep
        the forward-only behaviour untouched."""
        if not (cfg.revert_to_best and snapshot is not None):
            return None
        try:
            return snapshot()
        except Exception:
            return None

    def revert(token, steps: list, phase: str) -> bool:
        if not (cfg.revert_to_best and restore is not None and token is not None):
            return False
        try:
            restore(token)
            return True
        except Exception as exc:
            steps.append(event(f"revert-to-best FAILED ({exc})", phase))
            return False

    def _green(ev: SuiteEval) -> bool:
        return ev.result.compiled and ev.result.ran and ev.result.failed == 0

    def clusters_of(ev: SuiteEval) -> list:
        return select_clusters(cluster_failures(ev.failures), cfg.cluster_cap)

    # ── nodes ────────────────────────────────────────────────────────────────
    def memory_node(state):
        steps: list = list(seed.ctrl) if seed else []
        gs = slice_.get("source_graph_summary", {})
        steps.append(event(
            f"mutation graph: {gs.get('methods', '?')} methods, "
            f"{gs.get('edges', '?')} edges, "
            f"{gs.get('tests', '?')} tests", "memory"))
        entry = memory.get(target_fqn)
        steps.append(event(
            f"memory: HIT for {target_fqn} — trying the cached causal insight"
            if entry else
            f"memory: miss for {target_fqn} — full causal pass", "memory"))
        return {"cached": entry, "attempt": 0, "cur": initial,
                "best_failed": (seed.best_failed if seed else
                                (initial.result.failed if initial.result.ran else None)),
                # Entry worktree = the implement state (often the best; a bad fix
                # must be able to roll back TO it). Captured now, before any probe.
                "best_snapshot": snap(),
                "specs": "", "probe_lines": [], "graph": None, "root_rank": None,
                "beta_degraded": False, "gamma_degraded": False,
                "ranks": [(m, 0.0) for m in methods],
                "phase_traces": list(seed.phase_traces) if seed else [],
                "ctrl": steps}

    def cache_fix_node(state):
        steps: list = []
        f = do_phase("cache-fix",
                     cache_fix_prompt(cfg.target_label,
                                      state["cached"]["causal_graph"],
                                      clusters_of(state["cur"])),
                     ["read", "edit"], steps)
        classes = state["cached"].get("test_classes") or test_classes
        ev, _lines = run_subset(steps, "cache-fix", classes)
        cur = ev
        full_ran = False
        if _green(ev):
            cur = run_full(steps, "cache-fix")
            full_ran = True
        infra = (not ev.result.ran) or (full_ran and not cur.result.ran)
        if _green(cur) and full_ran:
            steps.append(event("cache-fix: cached insight fixed it — subset + "
                               "full suite green", "cache-fix"))
        elif cancelled():
            steps.append(event("cache-fix: run cancelled — keeping the cached "
                               "entry (staleness was not tested)", "cache-fix"))
        elif infra:
            steps.append(event("cache-fix: subset/full run infra failure — keeping "
                               "the cached entry (staleness was not tested); full "
                               "causal pass", "cache-fix"))
        else:
            memory.invalidate(target_fqn)
            steps.append(event("cache-fix: cached insight is STALE (tests still "
                               "red) — invalidated; full causal pass", "cache-fix"))
        old_bf = state["best_failed"]
        bf = (_track_best(cur, old_bf, productive) if full_ran else old_bf)
        best_snap = state.get("best_snapshot")
        if full_ran and bf is not None and (old_bf is None or bf < old_bf):
            best_snap = snap()                       # cache-fix reached a new best
        return {"cur": cur, "best_failed": bf, "best_snapshot": best_snap,
                "phase_traces": [("cache-fix", f.trace)], "ctrl": steps}

    def alpha_node(state):
        steps: list = []
        a = do_phase("alpha", alpha_prompt(slice_), ["read"], steps)
        specs = (a.text or "").strip()
        steps.append(event(
            f"alpha: contracts for {len(methods)} methods ({len(specs)} chars)"
            if specs else "alpha: EMPTY contracts — continuing without", "alpha"))
        return {"specs": specs, "phase_traces": [("alpha", a.trace)],
                "ctrl": steps}

    def beta_node(state):
        steps: list = []
        traces: list = []
        b = do_phase("beta", beta_prompt(slice_, state["specs"]), ["read", "edit"],
                     steps)
        traces.append(("beta", b.trace))
        ev, lines = run_subset(steps, "beta", test_classes)
        beta_ok = ev.result.compiled and ev.result.ran
        if not beta_ok and not cancelled():
            steps.append(event("beta: instrumented build broke — one repair "
                               "attempt", "beta"))
            r = do_phase("beta-repair", beta_repair_prompt(slice_), ["read", "edit"],
                         steps)
            traces.append(("beta-repair", r.trace))
            ev, lines = run_subset(steps, "beta", test_classes)
            beta_ok = ev.result.compiled and ev.result.ran
        removed = safe_strip(steps, "beta")
        if beta_ok:
            steps.append(event(
                f"beta: probes ran — {len(lines)} probe lines from the subset "
                f"({ev.result.passed} passed / {ev.result.failed} failed, "
                f"instrumented); {removed} probe lines stripped", "beta"))
        else:
            lines = []
            steps.append(event(
                "beta: instrumentation failed twice — degrading to a NO-LOGS "
                f"causal pass; {removed} probe lines stripped", "beta"))
        return {"probe_lines": lines, "beta_ok": beta_ok,
                "beta_degraded": (not beta_ok),
                "phase_traces": traces, "ctrl": steps}

    def gamma_node(state):
        steps: list = []
        traces: list = []
        prompt = gamma_prompt(slice_, state["specs"], state["probe_lines"])
        g1 = do_phase("gamma", prompt, ["read"], steps)
        traces.append(("gamma", g1.trace))
        graph = parse_causal_delta(g1.text)
        if graph is None and not cancelled():
            steps.append(event("gamma: unparseable causal graph — one "
                               "format-reminded retry", "gamma"))
            g2 = do_phase("gamma-retry", prompt + GAMMA_FORMAT_REMINDER,
                          ["read"], steps)
            traces.append(("gamma-retry", g2.trace))
            graph = parse_causal_delta(g2.text)
        if graph is None:
            ranks = [(m, 0.0) for m in methods]
            steps.append(event("gamma: still unparseable — degraded to "
                               "subgraph-order ranking (target first)", "gamma"))
            return {"graph": None, "ranks": ranks, "root_rank": None,
                    "gamma_degraded": True, "phase_traces": traces, "ctrl": steps}
        ranks = causal_rank(graph, methods)
        rr = root_rank(ranks, target_fqn)
        steps.append(event(
            f"gamma: causal delta graph with {len(graph.get('vertices', []))} "
            f"vertices / {len(graph.get('edges', []))} edges; CausalRank of "
            f"target = {rr}/{len(ranks)}", "gamma"))
        return {"graph": graph, "ranks": ranks, "root_rank": rr,
                "gamma_degraded": False, "phase_traces": traces, "ctrl": steps}

    def fix_node(state):
        steps: list = []
        attempt = state["attempt"] + 1
        ranks = state["ranks"]
        focus = ranks[min(attempt - 1, len(ranks) - 1)][0]
        f = do_phase(f"fix-{attempt}",
                     fix_prompt(cfg.target_label, target_fqn, state["graph"],
                                state["specs"], clusters_of(state["cur"]),
                                focus, attempt),
                     ["read", "edit"], steps)
        ev, _lines = run_subset(steps, f"fix-{attempt}", test_classes)
        cur = ev
        if _green(ev):
            steps.append(event(f"fix {attempt} (focus {focus}): subset GREEN — "
                               "running the full suite", f"fix-{attempt}"))
            cur = run_full(steps, f"fix-{attempt}")
            steps.append(event(
                f"fix {attempt}: full suite {cur.result.passed} passed / "
                f"{cur.result.failed} failed (compiled={cur.result.compiled})",
                f"fix-{attempt}"))
            old_bf = state["best_failed"]
            bf = _track_best(cur, old_bf, productive)
            best_snap = (snap() if bf is not None and (old_bf is None or bf < old_bf)
                         else state.get("best_snapshot"))   # capture a new best
        else:
            steps.append(event(
                f"fix {attempt} (focus {focus}): subset still red — "
                f"{ev.result.passed} passed / {ev.result.failed} failed",
                f"fix-{attempt}"))
            bf = state["best_failed"]
            best_snap = state.get("best_snapshot")
        return {"attempt": attempt, "cur": cur, "best_failed": bf,
                "best_snapshot": best_snap,
                "phase_traces": [(f"fix-{attempt}", f.trace)], "ctrl": steps}

    def finalize_node(state):
        steps: list = []
        cur = state["cur"]
        best = state["best_failed"]
        # revert_to_best: a fix that ended WORSE than the best-reached state is
        # rolled back, so the graded worktree is the best we achieved rather than
        # the last regression. No-op unless enabled AND the final state is worse.
        reverted = False
        if (not cancelled() and best is not None and cur.result.ran
                and cur.result.failed > best):
            reverted = revert(state.get("best_snapshot"), steps, "finalize")
        if cancelled():
            outcome = "cancelled"
        elif reverted:
            outcome = "green" if best == 0 else "stuck"   # graded state is now best
        elif _green(cur):
            outcome = "green"
        elif not cur.result.compiled:
            outcome = "compile-fail"
        else:
            outcome = "stuck"
        graph_to_save = state.get("graph") \
            or (state.get("cached") or {}).get("causal_graph")
        saved = ""
        if outcome == "green" and graph_to_save:
            memory.put(target_fqn, graph_to_save, test_classes)
            saved = " — causal insight saved to memory"
        note = " — reverted to best-reached worktree" if reverted else ""
        steps.append(event(f"finalized: {outcome}{saved}{note}: "
                     f"last {cur.result.passed} passed / {cur.result.failed} failed "
                     f"(best reached: {best} failed)", "finalize"))
        return {"outcome": outcome, "ctrl": steps}

    # ── edges ────────────────────────────────────────────────────────────────
    def after_memory(state):
        return "cache_fix" if state["cached"] else "alpha"

    def after_cache(state):
        return "finalize" if (_green(state["cur"]) or cancelled()) else "alpha"

    def after_fix(state):
        if _green(state["cur"]) or cancelled() \
                or state["attempt"] >= cfg.max_attempts:
            return "finalize"
        return "fix"

    g = StateGraph(RccState)
    g.add_node("memory", memory_node)
    g.add_node("cache_fix", cache_fix_node)
    g.add_node("alpha", alpha_node)
    g.add_node("beta", beta_node)
    g.add_node("gamma", gamma_node)
    g.add_node("fix", fix_node)
    g.add_node("finalize", finalize_node)
    g.add_edge(START, "memory")
    g.add_conditional_edges("memory", after_memory,
                            {"cache_fix": "cache_fix", "alpha": "alpha"})
    g.add_conditional_edges("cache_fix", after_cache,
                            {"finalize": "finalize", "alpha": "alpha"})
    g.add_edge("alpha", "beta")
    g.add_edge("beta", "gamma")
    g.add_edge("gamma", "fix")
    g.add_conditional_edges("fix", after_fix,
                            {"fix": "fix", "finalize": "finalize"})
    g.add_edge("finalize", END)
    app = g.compile()

    final = app.invoke({}, config={"recursion_limit": cfg.max_attempts * 2 + 20})

    try:
        tr = stitch(final.get("phase_traces", []), final.get("ctrl", []),
                    outcome=final.get("outcome"),
                    controller_test_runs=full_runs[0] + subset_runs[0],
                    accepted_rounds=productive[0], reverted_rounds=0,
                    best_failed_reached=final.get("best_failed"))
    except Exception as exc:  # pragma: no cover
        emit({"type": "controller", "phase": "finalize",
              "text": f"stitch FAILED ({exc})"})
        tr = Trace(steps=list(final.get("ctrl", [])), finished=True)
        tr.orchestration_outcome = final.get("outcome")
        tr.controller_test_runs = full_runs[0] + subset_runs[0]
        tr.accepted_rounds = productive[0]
        tr.reverted_rounds = 0
        tr.best_failed_reached = final.get("best_failed")
    tr.rcc_root_rank = final.get("root_rank")
    tr.rcc_memory_hit = bool(final.get("cached"))
    tr.rcc_beta_degraded = bool(final.get("beta_degraded"))
    tr.rcc_gamma_degraded = bool(final.get("gamma_degraded"))
    tr.rcc_subset_test_runs = subset_runs[0]
    return tr
