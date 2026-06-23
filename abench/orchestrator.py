"""Phased-orchestration core: a forced fix methodology over injected deps.

UNDERSTAND -> [PLAN] -> IMPLEMENT -> DIAGNOSE-loop -> finalize, with a
multi-factor regression gate (+ flaky re-confirm), git snapshot/revert, and a
stitched Trace. PURE: it never imports opencode or runs gradle — the caller
injects `phase_runner` (one scoped agent call) and `suite_runner` (compile+test).
Task specifics come from OrchestratorConfig; the orchestrator stays task-agnostic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from .failure_report import Cluster, TestFailure, cluster_failures, select_clusters
from .regression_gate import SuiteResult, decide
from .trace_model import Step, StepKind, Trace
from .trace_stitch import stitch


@dataclass
class PhaseOutcome:
    trace: Trace
    text: str            # agent's final message (the contract / plan); "" for edit phases


@dataclass
class SuiteEval:
    result: SuiteResult
    failures: list[TestFailure] = field(default_factory=list)


class PhaseRunner(Protocol):
    def __call__(self, phase: str, prompt: str, allowed_tools: list[str]) -> PhaseOutcome: ...


class SuiteRunner(Protocol):
    def __call__(self) -> SuiteEval: ...


@dataclass
class OrchestratorConfig:
    # Task-specific scaffolding (supplied per experiment, NOT hardcoded):
    contract_fields: list[str] = field(default_factory=list)   # aspect-words the contract should address
    target_label: str = "the target method"
    # Generic knobs:
    with_plan: bool = False
    min_understand_reads: int = 2
    min_contract_aspects: int = 2
    max_diagnose_iters: int = 8
    no_progress_limit: int = 2
    cluster_cap: int = 5


def _count_reads(trace: Trace) -> int:
    return sum(1 for s in trace.steps
               if s.kind == StepKind.TOOL_CALL and (s.tool_name in ("read", "grep")))


def contract_ok(outcome: PhaseOutcome, cfg: OrchestratorConfig) -> tuple[bool, str]:
    text = (outcome.text or "").strip()
    if len(text) < 40:
        return False, "contract is empty / too short"
    hits = sum(1 for a in cfg.contract_fields if a.lower() in text.lower())
    if hits < cfg.min_contract_aspects:
        return False, f"contract addresses too few aspects (matched {hits})"
    if _count_reads(outcome.trace) < cfg.min_understand_reads:
        return False, "did not read enough sources (callers/tests)"
    return True, "ok"


def plan_ok(outcome: PhaseOutcome) -> tuple[bool, str]:
    return (len((outcome.text or "").strip()) >= 30), "ok"


# ── prompt builders (generic mechanism; content driven by cfg/contract/clusters) ──

def understand_prompt(cfg: OrchestratorConfig) -> str:
    return (f"Study {cfg.target_label}. Read its callers AND a spread of tests "
            "from DIFFERENT test classes that exercise it. Then write a CONTRACT: "
            "what it must do across every case (overflow modes, indentation, "
            "wrapping, return value, edge cases). Do not edit code yet.")


def plan_prompt(cfg: OrchestratorConfig, contract: str) -> str:
    return ("Given this contract, sketch your implementation APPROACH, naming the "
            "concrete existing helpers/methods you will use.\n\nCONTRACT:\n" + contract)


def implement_prompt(cfg: OrchestratorConfig, contract: str, plan: str) -> str:
    body = "CONTRACT:\n" + contract + (("\n\nPLAN:\n" + plan) if plan else "")
    return f"Implement {cfg.target_label} to satisfy the contract.\n\n" + body


def _fmt_cluster(c: Cluster) -> str:
    r = c.representative
    head = f"- [{c.count}x, {r.type or r.kind}] {r.classname.rsplit('.', 1)[-1]}.{r.name}"
    if r.expected is not None and r.actual is not None:
        return head + f"\n    expected: {r.expected!r}\n    actual:   {r.actual!r}"
    return head + (f"\n    {r.message}" if r.message else "")


def diagnose_prompt(cfg: OrchestratorConfig, contract: str, plan: str,
                    clusters: list[Cluster]) -> str:
    body = "\n".join(_fmt_cluster(c) for c in clusters)
    return ("The full suite still fails. Here is ONE example per failure cluster "
            "(across classes). Find the COMMON root cause and make ONE fix to "
            f"{cfg.target_label} — do not curve-fit a single test.\n\n"
            f"FAILURE CLUSTERS:\n{body}\n\nCONTRACT (for reference):\n{contract}")


def fallback_contract(failures: list[TestFailure], cfg: OrchestratorConfig) -> str:
    names = ", ".join(sorted({f.classname.rsplit('.', 1)[-1] for f in failures})[:8])
    return (f"[auto] Contract for {cfg.target_label}, derived from failing tests: "
            f"satisfy {names}. Address: {', '.join(cfg.contract_fields)}.")


def _improved(before: SuiteResult, after: SuiteResult) -> bool:
    return decide(before, after)[0]


def run(
    cfg: OrchestratorConfig,
    *,
    phase_runner: PhaseRunner,
    suite_runner: SuiteRunner,
    snapshot: Callable[[], object],
    restore: Callable[[object], None],
) -> Trace:
    phase_traces: list[tuple[str, Trace]] = []
    ctrl: list[Step] = []
    clock = [0.0]
    test_runs = [0]
    accepted = [0]
    reverted = [0]

    def event(text: str, phase: str) -> None:
        clock[0] += 1.0
        ctrl.append(Step(kind=StepKind.CONTROLLER, ts=clock[0], turn=0, text=text, phase=phase))

    def run_suite() -> SuiteEval:
        test_runs[0] += 1
        return suite_runner()

    # Initial best = the starting (stub) state.
    best_tree = snapshot()
    base = run_suite()
    best = base
    event(f"baseline: {base.result.passed}p/{base.result.failed}f", "implement")

    # ── UNDERSTAND ────────────────────────────────────────────────────────
    u = phase_runner("understand", understand_prompt(cfg), ["read", "grep"])
    phase_traces.append(("understand", u.trace))
    ok, why = contract_ok(u, cfg)
    contract = u.text if ok else fallback_contract(base.failures, cfg)
    event(f"contract {'accepted' if ok else 'fallback: ' + why}", "understand")

    # ── PLAN (toggle) ─────────────────────────────────────────────────────
    plan = ""
    if cfg.with_plan:
        p = phase_runner("plan", plan_prompt(cfg, contract), ["read"])
        phase_traces.append(("plan", p.trace))
        okp, _ = plan_ok(p)
        plan = p.text if okp else ""
        event(f"plan {'accepted' if okp else 'empty'}", "plan")

    # ── IMPLEMENT ─────────────────────────────────────────────────────────
    im = phase_runner("implement", implement_prompt(cfg, contract, plan), ["read", "edit"])
    phase_traces.append(("implement", im.trace))
    ev = run_suite()
    if _improved(best.result, ev.result):
        best_tree = snapshot(); best = ev; accepted[0] += 1
        event(f"implement accepted: {ev.result.passed}p/{ev.result.failed}f", "implement")
    else:
        event(f"implement not accepted (compiled={ev.result.compiled})", "implement")

    # ── DIAGNOSE loop ─────────────────────────────────────────────────────
    no_progress = 0
    it = 0
    while not (best.result.compiled and best.result.failed == 0):
        if it >= cfg.max_diagnose_iters or no_progress >= cfg.no_progress_limit:
            break
        it += 1
        restore(best_tree)                     # always fix from the current best
        clusters = select_clusters(cluster_failures(best.failures), cfg.cluster_cap)
        d = phase_runner("diagnose", diagnose_prompt(cfg, contract, plan, clusters),
                         ["read", "edit", "verify"])
        phase_traces.append(("diagnose", d.trace))
        cand = run_suite()
        ok_gate, why = decide(best.result, cand.result)
        if not ok_gate:                        # flaky re-confirm before reverting
            cand = run_suite()
            ok_gate, why = decide(best.result, cand.result)
        if ok_gate:
            best_tree = snapshot(); best = cand; accepted[0] += 1; no_progress = 0
            event(f"round {it} accepted ({why})", "diagnose")
        else:
            reverted[0] += 1; no_progress += 1
            event(f"round {it} reverted ({why})", "diagnose")

    # ── finalize ──────────────────────────────────────────────────────────
    restore(best_tree)
    if best.result.compiled and best.result.failed == 0:
        outcome = "green"
    elif not best.result.compiled:
        outcome = "compile-fail"
    elif it >= cfg.max_diagnose_iters:
        outcome = "budget"
    else:
        outcome = "stuck"
    event(f"finalized: {outcome} ({best.result.passed}p/{best.result.failed}f)", "diagnose")

    return stitch(phase_traces, ctrl, outcome=outcome,
                  controller_test_runs=test_runs[0],
                  accepted_rounds=accepted[0], reverted_rounds=reverted[0])
