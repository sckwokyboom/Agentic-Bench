# Phased Orchestration — Plan 2: Orchestrator Core

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** The phase state machine (`UNDERSTAND → [PLAN] → IMPLEMENT → DIAGNOSE-loop → finalize`) that composes the Plan-1 utilities into one orchestrated run — as PURE logic over injected dependencies, so it's unit-testable with fakes (no opencode, no gradle, no container).

**Architecture:** `abench/orchestrator.py` takes injected `phase_runner` (one scoped opencode call → trace + agent text) and `suite_runner` (compile+test → `SuiteResult` + failures), plus `snapshot`/`restore` callables. It owns control-flow, gates, the regression-gated diagnose loop (with flaky re-confirm), budgets, and produces one stitched `Trace`. The REAL adapters (wrapping `run_task` per phase; running gradle in the sandbox; parsing JUnit XML) are Plan 3 — this plan never imports opencode or runs gradle.

**Tech Stack:** Python 3 stdlib + the Plan-1 modules (`failure_report`, `regression_gate`, `trace_stitch`, `trace_model`, `git_snapshot`). pytest with fakes.

Spec: `docs/superpowers/specs/2026-06-23-phased-orchestration-design.md`. Depends on Plan 1 (merged).

---

## File structure

- Create `abench/orchestrator.py` — interfaces + config + gates + prompt builders + `run()`.
- Create `tests/test_orchestrator.py` — gate tests + end-to-end run scenarios with fakes.

The orchestrator is **task-agnostic**: task specifics (the contract aspect-words, the target method label) arrive via `OrchestratorConfig`, never hardcoded.

---

## Task 1: Interfaces, config, gates, prompt builders

**Files:**
- Create: `abench/orchestrator.py`
- Create: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test** (`tests/test_orchestrator.py`)

```python
from abench.trace_model import Step, StepKind, Trace
from abench.orchestrator import (
    PhaseOutcome, OrchestratorConfig, contract_ok, plan_ok, diagnose_prompt,
)
from abench.failure_report import Cluster, TestFailure


def _trace_with_reads(n):
    steps = [Step(kind=StepKind.TOOL_CALL, ts=float(i), tool_name="read") for i in range(n)]
    return Trace(steps=steps)


_CFG = OrchestratorConfig(contract_fields=["WRAP", "SPAN", "indent"], min_understand_reads=2)


def test_contract_ok_requires_aspects_and_reads():
    good = PhaseOutcome(_trace_with_reads(2),
                        "Contract: handles WRAP and SPAN overflow with indent.")
    assert contract_ok(good, _CFG)[0] is True


def test_contract_rejected_when_too_few_aspects():
    bad = PhaseOutcome(_trace_with_reads(3),
                       "This describes the method behavior in plain prose only.")  # >=40 chars, 0 aspects
    ok, why = contract_ok(bad, _CFG)
    assert ok is False and "aspect" in why.lower()


def test_contract_rejected_when_not_enough_reads():
    bad = PhaseOutcome(_trace_with_reads(0),
                       "Contract: WRAP and SPAN with indent, lots of detail here.")
    ok, why = contract_ok(bad, _CFG)
    assert ok is False and "read" in why.lower()


def test_plan_ok_rejects_empty():
    assert plan_ok(PhaseOutcome(Trace(), ""))[0] is False
    assert plan_ok(PhaseOutcome(Trace(), "Use copy(BreakIterator) for WRAP; advance col for SPAN."))[0] is True


def test_diagnose_prompt_includes_one_example_per_cluster():
    clusters = [
        Cluster(signature="s1", severity=2,
                representative=TestFailure("IdxTest", "boom", "error",
                                           "java.lang.IndexOutOfBoundsException", "index 5"),
                count=3, members=["IdxTest.boom"]),
        Cluster(signature="s2", severity=1,
                representative=TestFailure("HelpTest", "tt", "failure",
                                           "org.junit.ComparisonFailure", "m", "  x [y]", "  x[y]"),
                count=7, members=["HelpTest.tt"]),
    ]
    p = diagnose_prompt(_CFG, "the contract", "the plan", clusters)
    assert "IndexOutOfBounds" in p and "ComparisonFailure" in p
    assert "  x [y]" in p and "  x[y]" in p          # expected-vs-actual surfaced
    assert "root cause" in p.lower()                 # asks for one root-cause fix
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_orchestrator.py -q`
Expected: FAIL — `ModuleNotFoundError: abench.orchestrator`.

- [ ] **Step 3: Implement interfaces + gates + prompts** (`abench/orchestrator.py`)

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_orchestrator.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add abench/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(orchestrator): phase interfaces, config, gates, prompt builders"
```

---

## Task 2: The `run()` phase machine + finalize/stitch

**Files:**
- Modify: `abench/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_orchestrator.py`)

```python
from abench.orchestrator import run, SuiteEval
from abench.regression_gate import SuiteResult


def _sr(passed, failed, compiled=True, ran=True, executed=None):
    executed = passed + failed if executed is None else executed
    return SuiteResult(compiled=compiled, ran=ran, executed=executed,
                       passed=passed, failed=failed)


def _eval(passed, failed, **kw):
    return SuiteEval(result=_sr(passed, failed, **kw), failures=[])


def _fake_phase(text_by_phase):
    def runner(phase, prompt, allowed_tools):
        return PhaseOutcome(_trace_with_reads(2), text_by_phase.get(phase, ""))
    return runner


def _fake_suite(seq):
    it = iter(seq)
    calls = {"n": 0}
    def runner():
        calls["n"] += 1
        return next(it)
    runner.calls = calls
    return runner


def _snap_restore():
    state = {"snaps": 0, "restores": 0, "tree": None}
    def snapshot():
        state["snaps"] += 1; state["tree"] = state["snaps"]; return state["tree"]
    def restore(tree):
        state["restores"] += 1; state["tree"] = tree
    return snapshot, restore, state


_CONTRACT = {"understand": "Contract: WRAP and SPAN overflow with indent handling, full detail."}


def test_run_green_when_implement_passes_everything():
    suite = _fake_suite([_eval(0, 100),     # baseline (stub: all fail) -> here modeled as 0 pass/100 fail
                         _eval(100, 0)])     # after implement: all pass
    snap, restore, _ = _snap_restore()
    t = run(_CFG, phase_runner=_fake_phase(_CONTRACT), suite_runner=suite,
            snapshot=snap, restore=restore)
    assert t.orchestration_outcome == "green"
    assert t.accepted_rounds == 1 and t.reverted_rounds == 0


def test_run_green_after_one_diagnose_round():
    suite = _fake_suite([_eval(0, 100),     # baseline
                         _eval(60, 40),      # after implement: better, accepted
                         _eval(100, 0)])     # diagnose round 1: all pass
    snap, restore, _ = _snap_restore()
    t = run(_CFG, phase_runner=_fake_phase(_CONTRACT), suite_runner=suite,
            snapshot=snap, restore=restore)
    assert t.orchestration_outcome == "green"
    assert t.accepted_rounds == 2          # implement + 1 diagnose


def test_run_stuck_when_no_round_improves():
    # implement helps; every diagnose round regresses -> reverts -> no_progress -> stuck
    suite = _fake_suite([_eval(0, 100),     # baseline
                         _eval(60, 40),      # implement accepted
                         _eval(55, 45), _eval(55, 45),   # round1 cand + flaky re-confirm: worse
                         _eval(50, 50), _eval(50, 50)])   # round2 cand + re-confirm: worse
    snap, restore, state = _snap_restore()
    t = run(_CFG, phase_runner=_fake_phase(_CONTRACT), suite_runner=suite,
            snapshot=snap, restore=restore)
    assert t.orchestration_outcome == "stuck"
    assert t.reverted_rounds == 2 and t.accepted_rounds == 1   # only implement accepted
    assert state["restores"] >= 1          # reverted to best


def test_run_flaky_regression_is_reconfirmed_then_accepted():
    # round1 candidate looks worse on first run, but re-confirm shows improvement -> accept
    suite = _fake_suite([_eval(0, 100),     # baseline
                         _eval(60, 40),      # implement accepted
                         _eval(58, 42),      # round1 first run: looks like a regression
                         _eval(100, 0)])     # re-confirm: actually all pass (flaky first run)
    snap, restore, _ = _snap_restore()
    t = run(_CFG, phase_runner=_fake_phase(_CONTRACT), suite_runner=suite,
            snapshot=snap, restore=restore)
    assert t.orchestration_outcome == "green"
    assert t.accepted_rounds == 2


def test_run_uses_fallback_contract_when_gate_fails():
    # understand returns an empty contract -> gate fails -> fallback used, run still proceeds
    suite = _fake_suite([_eval(0, 100), _eval(100, 0)])
    snap, restore, _ = _snap_restore()
    t = run(_CFG, phase_runner=_fake_phase({"understand": ""}), suite_runner=suite,
            snapshot=snap, restore=restore)
    assert t.orchestration_outcome == "green"
    # the understand phase + implement phase both appear, tagged
    phases = {s.phase for s in t.steps if s.phase}
    assert "understand" in phases and "implement" in phases
    # controller emitted CONTROLLER steps
    assert any(s.kind == StepKind.CONTROLLER for s in t.steps)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_orchestrator.py -q`
Expected: FAIL — `ImportError: cannot import name 'run'`.

- [ ] **Step 3: Implement `run()`** (append to `abench/orchestrator.py`)

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_orchestrator.py -q`
Expected: PASS (all gate + run tests).

- [ ] **Step 5: Commit**

```bash
git add abench/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(orchestrator): run() phase machine (gate, diagnose loop, flaky re-confirm, finalize/stitch)"
```

---

## Final: full orchestrator + Plan-1 suite green

- [ ] **Step 1:** Run `python3 -m pytest tests/test_orchestrator.py tests/test_failure_report.py tests/test_regression_gate.py tests/test_trace_stitch.py tests/test_git_snapshot.py tests/test_trace_model.py -q` → all PASS.

---

## Notes for Plan 3 (runner/config integration)

- Add `orchestration: str | None` + the task-scaffolding fields (`contract_fields`, `target_label`, `with_plan`) to `Condition`/experiment config (config.py).
- Build the REAL adapters and call `orchestrator.run`:
  - `phase_runner`: wrap `RealOpenCodeClient.run_task(workdir=…, system_prompt=…, model=…, user_message=prompt, agent_tools={t: True for t in allowed_tools} + others False, …)`; `text` = the last `assistant_text` step in the returned trace; resolve session-per-phase vs continued (open question).
  - `suite_runner`: run `:compileJava` (→ `compiled`) then `:test --continue` in the sandbox workdir; parse stdout via `verify_parsers.parse_gradle_output` (counts/executed) + `failure_report.parse_junit_dir(build/test-results/test)` (failures); flaky re-confirm may re-run only the failing tests for speed.
  - `snapshot`/`restore`: bind `git_snapshot.snapshot/restore` to the run workdir; enforce `forbidden_changes(allowed_prefixes)` (revert + flag violations).
  - Container/daemon/cache determinism across the controller's repeated suite runs (open question).
- Branch `runner.py` to `orchestrator.run` when `orchestration` is set; baseline path untouched. Downstream (trace.json, verify, metrics) unchanged — `run()` already returns a stitched `Trace`.
