"""LangGraph implementation of the phased orchestrator — PARITY with
orchestrator.run (forward-only). opencode stays the agent; this replaces ONLY the
control-flow + state. Same injected-deps signature, same stitched Trace. Selected
via ABENCH_ORCHESTRATOR=langgraph (see runner._select_orchestrator)."""
from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from .failure_report import cluster_failures, select_clusters
from .orchestrator import (
    _MAX_CONTRACT_CHARS,
    _MAX_PLAN_CHARS,
    OrchestratorConfig,
    PhaseOutcome,
    SuiteEval,
    _cap,
    _track_best,
    contract_ok,
    diagnose_prompt,
    fallback_contract,
    implement_prompt,
    plan_ok,
    plan_prompt,
    understand_prompt,
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
              on_event=None, in_blast_radius=None, read_evidence=None, cancel_event=None) -> Trace:
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

    def cancelled() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    def run_suite(steps: list, phase: str = "implement") -> SuiteEval:
        test_runs[0] += 1
        try:
            return suite_runner()
        except Exception as exc:
            steps.append(event(f"suite run FAILED ({exc})", phase))
            return SuiteEval(result=SuiteResult(compiled=False, ran=False, executed=0,
                                                passed=0, failed=0))

    def do_phase(name: str, prompt: str, tools: list, steps: list) -> PhaseOutcome:
        if cancelled():                          # don't launch a new phase after cancel
            steps.append(event(f"run cancelled — skipping {name}", name))
            return PhaseOutcome(trace=Trace(), text="")
        emit({"type": "phase.start", "phase": name})
        emit({"type": "phase.prompt", "phase": name, "text": prompt})
        try:
            return phase_runner(name, prompt, tools)
        except Exception as exc:
            steps.append(event(f"phase {name} FAILED ({exc}); continuing degraded", name))
            return PhaseOutcome(trace=Trace(), text="")

    def baseline_node(state):
        steps: list = []
        base = run_suite(steps, "implement")
        bf = base.result.failed if base.result.ran else None
        steps.append(event(f"ran baseline test suite (stub, before any edits): "
                           f"{base.result.passed} passed / {base.result.failed} failed", "implement"))
        return {"cur": base, "best_failed": bf, "it": 0, "no_progress": 0,
                "card": None, "contract": "", "plan": "", "ctrl": steps}

    def understand_node(state):
        steps: list = []
        u = do_phase("understand", understand_prompt(cfg), ["read", "grep"], steps)
        ok, why = contract_ok(u, cfg)
        contract = (_cap(u.text, _MAX_CONTRACT_CHARS) if ok
                    else fallback_contract(state["cur"].failures, cfg))
        steps.append(event("agent's contract accepted (its spec of the method's required behaviour)"
                           if ok else f"agent's contract rejected ({why}) — using an auto-derived fallback",
                           "understand"))
        return {"contract": contract, "phase_traces": [("understand", u.trace)], "ctrl": steps}

    def plan_node(state):
        steps: list = []
        p = do_phase("plan", plan_prompt(cfg, state["contract"]), ["read"], steps)
        okp, _ = plan_ok(p)
        plan = _cap(p.text, _MAX_PLAN_CHARS) if okp else ""
        steps.append(event("agent's plan accepted (its approach + helpers to use)"
                           if okp else "agent's plan empty — proceeding without one", "plan"))
        return {"plan": plan, "phase_traces": [("plan", p.trace)], "ctrl": steps}

    def implement_node(state):
        steps: list = []
        im = do_phase("implement", implement_prompt(cfg, state["contract"], state["plan"]),
                      ["read", "edit"], steps)
        cur = run_suite(steps, "implement")
        bf = _track_best(cur, state["best_failed"], productive)
        steps.append(event(f"implement done — {cur.result.passed} passed / {cur.result.failed} failed "
                           f"(compiled={cur.result.compiled})", "implement"))
        return {"cur": cur, "best_failed": bf, "phase_traces": [("implement", im.trace)], "ctrl": steps}

    def diagnose_node(state):
        steps: list = []
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
        if cancelled():
            outcome = "cancelled"
        elif cur.result.compiled and cur.result.failed == 0:
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
        # node is "plan_phase" (LangGraph forbids a node name == a state key, and
        # "plan" is a state field).
        return "plan_phase" if cfg.with_plan else "implement"

    def cont(state):
        cur = state["cur"]
        green = cur.result.compiled and cur.result.failed == 0
        if (not green) and state["it"] < cfg.max_diagnose_iters \
                and state["no_progress"] < cfg.no_progress_limit and not cancelled():
            return "diagnose"
        return "finalize"

    g = StateGraph(OrchState)
    g.add_node("baseline", baseline_node)
    g.add_node("understand", understand_node)
    g.add_node("plan_phase", plan_node)
    g.add_node("implement", implement_node)
    g.add_node("diagnose", diagnose_node)
    g.add_node("finalize", finalize_node)
    g.add_edge(START, "baseline")
    g.add_edge("baseline", "understand")
    g.add_conditional_edges("understand", after_understand,
                            {"plan_phase": "plan_phase", "implement": "implement"})
    g.add_edge("plan_phase", "implement")
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
