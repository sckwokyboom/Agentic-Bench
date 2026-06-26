# LangGraph Orchestrator Migration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reproduce the current forward-only phased orchestrator (`orchestrator.run`) as a LangGraph `StateGraph` (`orchestrator_graph.run_graph`), selectable via `ABENCH_ORCHESTRATOR=langgraph`, validated equal-by-trace — parity first, before any new orchestration variants.

**Architecture:** opencode stays the agent. A thin `StateGraph` replaces ONLY `run()`'s control-flow + state; nodes call the unchanged adapters and shared pure helpers (prompts/gates/`_track_best`/`stitch`). Same injected-deps signature, same stitched `Trace`. `orchestrator.py` is untouched and remains the default.

**Tech Stack:** Python, LangGraph (optional extra `abench[langgraph]`, narrow surface: `StateGraph` + `operator.add` reducers; NOT LangChain model/tool abstractions).

Spec: `docs/superpowers/specs/2026-06-26-langgraph-orchestrator-migration-design.md`.

---

## File Structure

- Modify: `pyproject.toml` — add the optional `langgraph` extra.
- Create: `abench/orchestrator_graph.py` — `OrchState`, nodes, `run_graph` (graph build + invoke + `stitch`).
- Create: `tests/test_orchestrator_graph_parity.py` — run `run()` and `run_graph()` on identical fakes, assert Trace equivalence.
- Modify: `abench/runner.py` — `_select_orchestrator()` switch (env-driven), used in the orchestration branch.
- Modify: `tests/test_runner.py` (or a new `tests/test_orchestrator_select.py`) — unit-test the switch.

---

## Task 1: langgraph dep + the graph module (parity on the simplest scenario)

**Files:**
- Modify: `pyproject.toml`
- Create: `abench/orchestrator_graph.py`
- Test: `tests/test_orchestrator_graph_parity.py`

- [ ] **Step 1: Add the optional extra + install**

In `pyproject.toml`, under `[project.optional-dependencies]` (create the table if absent), add:
```toml
langgraph = ["langgraph>=0.2,<0.4"]
```
Run: `pip install -e '.[langgraph]'`
Then verify: `python3 -c "from langgraph.graph import StateGraph, START, END; print('ok')"` → prints `ok`.

- [ ] **Step 2: Write the parity harness + the first parity test**

Create `tests/test_orchestrator_graph_parity.py`:
```python
import pytest

pytest.importorskip("langgraph")  # skip cleanly when the extra isn't installed

from abench.orchestrator import run
from abench.orchestrator_graph import run_graph
from abench.metrics import MetricsConfig, extract
from abench.trace_model import StepKind
from tests.test_orchestrator import (
    _fake_phase, _fake_suite, _snap_restore, _eval, _trace_with_reads,
    _CFG, _CONTRACT, PhaseOutcome,
)
from abench.failure_report import TestFailure
from abench.orchestrator import SuiteEval, OrchestratorConfig
from abench.regression_gate import SuiteResult


_M = MetricsConfig(test_command_patterns=[], shell_tool_names=[],
                   read_tool_names=[], search_tool_names=[], command_arg_keys=[])


def _equiv(t, g):
    """Assert the Python run() trace `t` and the LangGraph trace `g` are equivalent."""
    assert t.orchestration_outcome == g.orchestration_outcome, "outcome"
    assert t.accepted_rounds == g.accepted_rounds, "accepted_rounds"
    assert t.reverted_rounds == g.reverted_rounds == 0, "reverted_rounds"
    assert t.best_failed_reached == g.best_failed_reached, "best_failed_reached"
    ct = [s.text for s in t.steps if s.kind == StepKind.CONTROLLER]
    cg = [s.text for s in g.steps if s.kind == StepKind.CONTROLLER]
    assert ct == cg, f"controller events differ:\n  py={ct}\n  lg={cg}"
    assert extract(t, "", _M)["n_steps"] == extract(g, "", _M)["n_steps"], "n_steps"


def _both(make_deps, cfg=_CFG):
    # Each orchestrator consumes its own fresh fakes (the suite fake holds an iterator).
    return run(cfg, **make_deps()), run_graph(cfg, **make_deps())


def test_parity_green_on_implement():
    def make():
        s, r, _ = _snap_restore()
        return dict(phase_runner=_fake_phase(_CONTRACT),
                    suite_runner=_fake_suite([_eval(0, 100), _eval(100, 0)]),
                    snapshot=s, restore=r)
    _equiv(*_both(make))
```

- [ ] **Step 3: Run it — expect failure (no `run_graph`)**

Run: `python3 -m pytest tests/test_orchestrator_graph_parity.py -q`
Expected: collection/import error — `abench.orchestrator_graph` does not exist.

- [ ] **Step 4: Implement `abench/orchestrator_graph.py`**

```python
"""LangGraph implementation of the phased orchestrator — PARITY with
orchestrator.run (forward-only). opencode stays the agent; this replaces ONLY the
control-flow + state. Same injected-deps signature, same stitched Trace. Selected
via ABENCH_ORCHESTRATOR=langgraph (see runner._select_orchestrator)."""
from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from .failure_report import cluster_failures, select_clusters
from .orchestrator import (
    OrchestratorConfig, PhaseOutcome, SuiteEval, _cap, _track_best,
    _MAX_CONTRACT_CHARS, _MAX_PLAN_CHARS,
    contract_ok, diagnose_prompt, fallback_contract, implement_prompt,
    plan_ok, plan_prompt, understand_prompt,
)
from .regression_gate import SuiteResult
from .trace_model import Step, StepKind, Trace
from .trace_stitch import stitch


class OrchState(TypedDict, total=False):
    contract: str
    plan: str
    cur: SuiteEval
    card: object          # str | None
    it: int
    no_progress: int
    best_failed: object   # int | None
    phase_traces: Annotated[list, operator.add]
    ctrl: Annotated[list, operator.add]
    outcome: object       # str | None


def run_graph(cfg: OrchestratorConfig, *, phase_runner, suite_runner, snapshot, restore,
              on_event=None, in_blast_radius=None, read_evidence=None) -> Trace:
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("ABENCH_ORCHESTRATOR=langgraph requires the optional dep: "
                           "pip install -e '.[langgraph]'") from exc

    # Accumulators that only feed stitch() — closure-mutable, NOT inter-node state.
    clock = [0.0]
    test_runs = [0]
    productive = [0]

    def emit(payload: dict) -> None:
        if on_event is not None:
            try:
                on_event(payload)
            except Exception:
                pass

    def event(text: str, phase: str) -> Step:
        clock[0] += 1.0
        emit({"type": "controller", "phase": phase, "text": text})
        return Step(kind=StepKind.CONTROLLER, ts=clock[0], turn=0, text=text, phase=phase)

    def run_suite(steps: list, phase: str = "implement") -> SuiteEval:
        test_runs[0] += 1
        try:
            return suite_runner()
        except Exception as exc:
            steps.append(event(f"suite run FAILED ({exc})", phase))
            return SuiteEval(result=SuiteResult(compiled=False, ran=False, executed=0,
                                                passed=0, failed=0))

    def do_phase(name: str, prompt: str, tools: list, steps: list) -> PhaseOutcome:
        emit({"type": "phase.start", "phase": name})
        emit({"type": "phase.prompt", "phase": name, "text": prompt})
        try:
            return phase_runner(name, prompt, tools)
        except Exception as exc:
            steps.append(event(f"phase {name} FAILED ({exc}); continuing degraded", name))
            return PhaseOutcome(trace=Trace(), text="")

    def baseline_node(state):
        steps = []
        base = run_suite(steps, "implement")
        bf = base.result.failed if base.result.ran else None
        steps.append(event(f"ran baseline test suite (stub, before any edits): "
                           f"{base.result.passed} passed / {base.result.failed} failed", "implement"))
        return {"cur": base, "best_failed": bf, "it": 0, "no_progress": 0,
                "card": None, "contract": "", "plan": "", "ctrl": steps}

    def understand_node(state):
        steps = []
        u = do_phase("understand", understand_prompt(cfg), ["read", "grep"], steps)
        ok, why = contract_ok(u, cfg)
        contract = (_cap(u.text, _MAX_CONTRACT_CHARS) if ok
                    else fallback_contract(state["cur"].failures, cfg))
        steps.append(event("agent's contract accepted (its spec of the method's required behaviour)"
                           if ok else f"agent's contract rejected ({why}) — using an auto-derived fallback",
                           "understand"))
        return {"contract": contract, "phase_traces": [("understand", u.trace)], "ctrl": steps}

    def plan_node(state):
        steps = []
        p = do_phase("plan", plan_prompt(cfg, state["contract"]), ["read"], steps)
        okp, _ = plan_ok(p)
        plan = _cap(p.text, _MAX_PLAN_CHARS) if okp else ""
        steps.append(event("agent's plan accepted (its approach + helpers to use)"
                           if okp else "agent's plan empty — proceeding without one", "plan"))
        return {"plan": plan, "phase_traces": [("plan", p.trace)], "ctrl": steps}

    def implement_node(state):
        steps = []
        im = do_phase("implement", implement_prompt(cfg, state["contract"], state["plan"]),
                      ["read", "edit"], steps)
        cur = run_suite(steps, "implement")
        bf = _track_best(cur, state["best_failed"], productive)
        steps.append(event(f"implement done — {cur.result.passed} passed / {cur.result.failed} failed "
                           f"(compiled={cur.result.compiled})", "implement"))
        return {"cur": cur, "best_failed": bf, "phase_traces": [("implement", im.trace)], "ctrl": steps}

    def diagnose_node(state):
        steps = []
        it = state["it"] + 1
        card = None
        if read_evidence is not None:
            try:
                card = read_evidence()
            except Exception:
                card = None
            if card:
                steps.append(event(f"runtime evidence: injected {len(card.splitlines())}-line card "
                                   "(actual args + call corridor + throw, captured this run)", "diagnose"))
        all_clusters = cluster_failures(state["cur"].failures)
        graph_focused = False
        if in_blast_radius is not None:
            in_r = [c for c in all_clusters if in_blast_radius(c.representative)]
            if in_r:
                steps.append(event(f"graph: focusing diagnose on {len(in_r)}/{len(all_clusters)} "
                                   f"failure clusters inside {cfg.target_label}'s blast radius", "diagnose"))
                all_clusters = in_r
                graph_focused = True
            else:
                steps.append(event(f"graph: no failing clusters in {cfg.target_label}'s blast radius "
                                   f"— using all {len(all_clusters)}", "diagnose"))
        clusters = select_clusters(all_clusters, cfg.cluster_cap)
        d = do_phase("diagnose",
                     diagnose_prompt(cfg, state["contract"], state["plan"], clusters,
                                     graph_focused=graph_focused, evidence_card=card),
                     ["read", "edit", "verify"], steps)
        prev_best = state["best_failed"]
        cur = run_suite(steps, "diagnose")
        bf = _track_best(cur, prev_best, productive)
        if bf is not None and (prev_best is None or bf < prev_best):
            no_progress = 0
            steps.append(event(f"diagnose round {it}: {cur.result.passed} passed / {cur.result.failed} "
                               f"failed — new best ({bf}); kept (no revert)", "diagnose"))
        else:
            no_progress = state["no_progress"] + 1
            steps.append(event(f"diagnose round {it}: {cur.result.passed} passed / {cur.result.failed} "
                               f"failed — no new best ({no_progress}/{cfg.no_progress_limit}); "
                               "kept (no revert)", "diagnose"))
        return {"it": it, "no_progress": no_progress, "best_failed": bf, "cur": cur, "card": card,
                "phase_traces": [("diagnose", d.trace)], "ctrl": steps}

    def finalize_node(state):
        cur = state["cur"]
        if cur.result.compiled and cur.result.failed == 0:
            outcome = "green"
        elif not cur.result.compiled:
            outcome = "compile-fail"
        elif state["it"] >= cfg.max_diagnose_iters:
            outcome = "budget"
        else:
            outcome = "stuck"
        step = event(f"finalized: {outcome} — final state kept as-is (no revert): "
                     f"{cur.result.passed} passed / {cur.result.failed} failed "
                     f"(best reached this run: {state['best_failed']} failed)", "diagnose")
        return {"outcome": outcome, "ctrl": [step]}

    def after_understand(state):
        return "plan" if cfg.with_plan else "implement"

    def cont(state):
        cur = state["cur"]
        green = cur.result.compiled and cur.result.failed == 0
        if (not green) and state["it"] < cfg.max_diagnose_iters and state["no_progress"] < cfg.no_progress_limit:
            return "diagnose"
        return "finalize"

    g = StateGraph(OrchState)
    g.add_node("baseline", baseline_node)
    g.add_node("understand", understand_node)
    g.add_node("plan", plan_node)
    g.add_node("implement", implement_node)
    g.add_node("diagnose", diagnose_node)
    g.add_node("finalize", finalize_node)
    g.add_edge(START, "baseline")
    g.add_edge("baseline", "understand")
    g.add_conditional_edges("understand", after_understand,
                            {"plan": "plan", "implement": "implement"})
    g.add_edge("plan", "implement")
    g.add_conditional_edges("implement", cont, {"diagnose": "diagnose", "finalize": "finalize"})
    g.add_conditional_edges("diagnose", cont, {"diagnose": "diagnose", "finalize": "finalize"})
    g.add_edge("finalize", END)
    app = g.compile()

    final = app.invoke({}, config={"recursion_limit": cfg.max_diagnose_iters * 2 + 20})

    try:
        return stitch(final.get("phase_traces", []), final.get("ctrl", []),
                      outcome=final.get("outcome"), controller_test_runs=test_runs[0],
                      accepted_rounds=productive[0], reverted_rounds=0,
                      best_failed_reached=final.get("best_failed"))
    except Exception as exc:  # pragma: no cover
        emit({"type": "controller", "phase": "diagnose", "text": f"stitch FAILED ({exc})"})
        tr = Trace(steps=list(final.get("ctrl", [])), finished=True)
        tr.orchestration_outcome = final.get("outcome")
        tr.controller_test_runs = test_runs[0]
        tr.accepted_rounds = productive[0]
        tr.reverted_rounds = 0
        tr.best_failed_reached = final.get("best_failed")
        return tr
```

- [ ] **Step 5: Run the first parity test — expect PASS**

Run: `python3 -m pytest tests/test_orchestrator_graph_parity.py -q`
Expected: PASS (1 test). If it fails on `controller events differ`, the node emitted an event whose text/order diverges from `run()` — fix the node's event string/order to match `orchestrator.py` exactly.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml abench/orchestrator_graph.py tests/test_orchestrator_graph_parity.py
git commit -m "feat(langgraph): StateGraph phased orchestrator (parity scaffold + green-on-implement)"
```

---

## Task 2: Parity coverage — diagnose loop + all variants

**Files:**
- Modify: `tests/test_orchestrator_graph_parity.py`

- [ ] **Step 1: Add parity tests for every run() scenario** (append)

```python
def test_parity_green_after_one_diagnose():
    def make():
        s, r, _ = _snap_restore()
        return dict(phase_runner=_fake_phase(_CONTRACT),
                    suite_runner=_fake_suite([_eval(0, 100), _eval(60, 40), _eval(100, 0)]),
                    snapshot=s, restore=r)
    _equiv(*_both(make))


def test_parity_stuck_no_progress():
    def make():
        s, r, _ = _snap_restore()
        return dict(phase_runner=_fake_phase(_CONTRACT),
                    suite_runner=_fake_suite([_eval(0, 100), _eval(60, 40), _eval(55, 45),
                                              _eval(55, 45), _eval(50, 50), _eval(50, 50)]),
                    snapshot=s, restore=r)
    _equiv(*_both(make))


def test_parity_never_reverts():
    def make():
        s, r, _ = _snap_restore()
        return dict(phase_runner=_fake_phase(_CONTRACT),
                    suite_runner=_fake_suite([_eval(50, 50)] * 40), snapshot=s, restore=r)
    _equiv(*_both(make))


def test_parity_fallback_contract():
    def make():
        s, r, _ = _snap_restore()
        return dict(phase_runner=_fake_phase({"understand": ""}),
                    suite_runner=_fake_suite([_eval(0, 100), _eval(100, 0)]), snapshot=s, restore=r)
    _equiv(*_both(make))


def test_parity_with_plan():
    cfg = OrchestratorConfig(contract_fields=["WRAP", "SPAN", "indent"],
                             min_understand_reads=2, with_plan=True)
    contract = dict(_CONTRACT, plan="Use copy(BreakIterator) for WRAP; advance col for SPAN.")

    def make():
        s, r, _ = _snap_restore()
        return dict(phase_runner=_fake_phase(contract),
                    suite_runner=_fake_suite([_eval(0, 100), _eval(100, 0)]), snapshot=s, restore=r)
    _equiv(*_both(make, cfg))


def test_parity_graph_focus():
    in_f = TestFailure(classname="picocli.HelpTest", name="inRadius", kind="failure")
    out_f = TestFailure(classname="picocli.OtherTest", name="outside", kind="error",
                        type="java.lang.NullPointerException")

    def make():
        s, r, _ = _snap_restore()
        return dict(phase_runner=_fake_phase(_CONTRACT),
                    suite_runner=lambda: SuiteEval(result=__import__("abench.regression_gate",
                        fromlist=["SuiteResult"]).SuiteResult(compiled=True, ran=True, executed=2,
                        passed=0, failed=2), failures=[in_f, out_f]),
                    snapshot=s, restore=r,
                    in_blast_radius=lambda f: f.name == "inRadius")
    _equiv(*_both(make))


def test_parity_runtime_card():
    def make():
        s, r, _ = _snap_restore()
        return dict(phase_runner=_fake_phase(_CONTRACT),
                    suite_runner=_fake_suite([_eval(0, 100), _eval(60, 40), _eval(100, 0)]),
                    snapshot=s, restore=r,
                    read_evidence=lambda: "RUNTIME EVIDENCE for TextTable.putValue: args [0,0]")
    _equiv(*_both(make))


def test_parity_failing_phases():
    def boom_phase(name, prompt, tools):
        raise RuntimeError(f"{name} boom")

    def make():
        s, r, _ = _snap_restore()
        return dict(phase_runner=boom_phase, suite_runner=_fake_suite([_eval(0, 100)] * 30),
                    snapshot=s, restore=r)
    _equiv(*_both(make))


def test_parity_failing_suite():
    def boom(*_a):
        raise RuntimeError("infra boom")

    def make():
        return dict(phase_runner=_fake_phase(_CONTRACT), suite_runner=boom,
                    snapshot=boom, restore=boom)
    _equiv(*_both(make))
```

> Note on `test_parity_graph_focus`: the fake suite returns the SAME failures on every call (never green), so both orchestrators loop until the no_progress cap — identically. The inline `SuiteResult` import keeps the fake self-contained.

- [ ] **Step 2: Run all parity tests**

Run: `python3 -m pytest tests/test_orchestrator_graph_parity.py -q`
Expected: PASS (10 tests). Any failure prints the diverging field (outcome / controller events / n_steps / best_failed) — fix the corresponding node in `orchestrator_graph.py` to match `orchestrator.py` exactly (same event text, same order, same counter logic). Do NOT change `orchestrator.py`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_orchestrator_graph_parity.py
git commit -m "test(langgraph): full parity coverage (diagnose loop, plan, graph-focus, runtime-card, degrade)"
```

---

## Task 3: Runner switch (`ABENCH_ORCHESTRATOR`)

**Files:**
- Modify: `abench/runner.py`
- Test: `tests/test_orchestrator_select.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_orchestrator_select.py`:
```python
from abench.runner import _select_orchestrator


def test_select_defaults_to_python(monkeypatch):
    monkeypatch.delenv("ABENCH_ORCHESTRATOR", raising=False)
    from abench.orchestrator import run as py
    assert _select_orchestrator() is py


def test_select_langgraph_when_env_set(monkeypatch):
    monkeypatch.setenv("ABENCH_ORCHESTRATOR", "langgraph")
    from abench.orchestrator_graph import run_graph
    assert _select_orchestrator() is run_graph
```

- [ ] **Step 2: Run it — expect failure**

Run: `python3 -m pytest tests/test_orchestrator_select.py -q`
Expected: FAIL — `_select_orchestrator` not defined.

- [ ] **Step 3: Add `_select_orchestrator` + use it in the orchestration branch**

Add at module level in `abench/runner.py` (near `_runtime_probe_jar`):
```python
def _select_orchestrator():
    """Pick the phased orchestrator implementation. Default = the Python run();
    ABENCH_ORCHESTRATOR=langgraph → the LangGraph run_graph (drop-in, same signature)."""
    import os
    if os.environ.get("ABENCH_ORCHESTRATOR") == "langgraph":
        from .orchestrator_graph import run_graph
        return run_graph
    from .orchestrator import run as _run_py
    return _run_py
```
In the orchestration branch of `_run_one`, replace the import `from .orchestrator import run as _orchestrate` with:
```python
                    _orchestrate = _select_orchestrator()
```
(Everything else — building `phase_runner`/`suite_runner`/`in_blast_radius`/`read_evidence` and the `_orchestrate(...)` call — is unchanged; signatures match.)

- [ ] **Step 4: Run the test — expect PASS**

Run: `python3 -m pytest tests/test_orchestrator_select.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the full unit suite (no regressions)**

Run: `python3 -m pytest tests/test_orchestrator.py tests/test_orchestrator_graph_parity.py tests/test_orchestrator_select.py tests/test_metrics.py -q`
Expected: all PASS (parity + existing orchestrator + metrics).

- [ ] **Step 6: Commit**

```bash
git add abench/runner.py tests/test_orchestrator_select.py
git commit -m "feat(langgraph): ABENCH_ORCHESTRATOR switch (python default | langgraph)"
```

---

## Task 4: E2E smoke + cutover (WSL, manual)

**Files:** none (operational verification).

- [ ] **Step 1: Build/install on the WSL box**

`git pull` + `pip install -e '.[langgraph]'` + restart abench host-python.

- [ ] **Step 2: Run ONE condition through both orchestrators**

Run the SAME condition (e.g. `phased`) twice via the UI/CLI:
- default (`ABENCH_ORCHESTRATOR` unset) → Python `run()`.
- `ABENCH_ORCHESTRATOR=langgraph` → the graph.

- [ ] **Step 3: Compare the two `trace.json`**

Confirm equal: `orchestration_outcome`, metrics (`n_steps`, `accepted_rounds`, `reverted_rounds`, `best_failed_reached`), and the ordered list of CONTROLLER step texts. Real opencode/gradle timing differs, but the controller-driven structure + outcome must match.

- [ ] **Step 4: Cutover decision (record, don't auto-flip)**

If unit parity (Tasks 1–2) is green AND the e2e smoke matches → the graph is trusted. Record this in the spec/README. The default stays Python until you explicitly flip it; new orchestration variants are then built on `orchestrator_graph.py`.

---

## Self-Review

**Spec coverage:**
- §1 State schema → `OrchState` + closure accumulators (Task 1 Step 4). ✓
- §2 Nodes/edges → six nodes + START/baseline/understand/[plan]/implement/diagnose-loop/finalize/END (Task 1). ✓
- §3 Switch + trace-equivalence → `_select_orchestrator` (Task 3) + `_equiv` parity assert + shared `stitch` (Tasks 1–2). ✓
- §4 Location/deps → `orchestrator_graph.py` imports shared helpers; `langgraph` optional extra + lazy import (Task 1). ✓
- §5 Parity testing → unit parity (Tasks 1–2, `importorskip`) + e2e smoke (Task 4). ✓

**Placeholder scan:** none — every step has runnable code/commands; the full graph module is inline.

**Type consistency:** `run_graph` signature == `orchestrator.run` (phase_runner, suite_runner, snapshot, restore, on_event, in_blast_radius, read_evidence). Imported helpers (`understand_prompt`/`plan_prompt`/`implement_prompt`/`diagnose_prompt`, `contract_ok`, `plan_ok`, `fallback_contract`, `_track_best`, `_cap`, `cluster_failures`, `select_clusters`, `stitch`) match `orchestrator.py`/`failure_report.py`/`trace_stitch.py` exactly. Event-text strings copied verbatim from the post-forward-only `orchestrator.py` (parity asserted in Task 2).

**Known risk (caught by Task 2, not a plan defect):** if any node's event text/order drifts from `orchestrator.py`, `_equiv`'s ordered-text assertion fails and names the diverging field — fix the node, never `orchestrator.py`.
