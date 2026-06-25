from abench.trace_model import Step, StepKind, Trace
from abench.orchestrator import (
    PhaseOutcome, SuiteEval, OrchestratorConfig, contract_ok, plan_ok,
    diagnose_prompt, run,
)
from abench.failure_report import Cluster, TestFailure
from abench.regression_gate import SuiteResult


def _trace_with_reads(n):
    steps = [Step(kind=StepKind.TOOL_CALL, ts=float(i), tool_name="read") for i in range(n)]
    return Trace(steps=steps)


_CFG = OrchestratorConfig(contract_fields=["WRAP", "SPAN", "indent"], min_understand_reads=2)


# ── gates / prompts ───────────────────────────────────────────────────────

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


# ── run() scenarios (fakes) ───────────────────────────────────────────────

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
    def runner():
        return next(it)
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
    suite = _fake_suite([_eval(0, 100), _eval(100, 0)])
    snap, restore, _ = _snap_restore()
    t = run(_CFG, phase_runner=_fake_phase(_CONTRACT), suite_runner=suite,
            snapshot=snap, restore=restore)
    assert t.orchestration_outcome == "green"
    assert t.accepted_rounds == 1 and t.reverted_rounds == 0


def test_run_emits_phase_and_controller_events_for_live_viz():
    """on_event (the live-viz sink) gets a phase.start per hand-off + a controller
    event per controller action — exactly what the live stream renders. It must
    NOT affect the returned trace's outcome/counts (viz-only)."""
    suite = _fake_suite([_eval(0, 100), _eval(100, 0)])
    snap, restore, _ = _snap_restore()
    events: list[dict] = []
    t = run(_CFG, phase_runner=_fake_phase(_CONTRACT), suite_runner=suite,
            snapshot=snap, restore=restore, on_event=events.append)
    kinds = [e["type"] for e in events]
    assert "phase.start" in kinds and "controller" in kinds
    phases = [e["phase"] for e in events if e["type"] == "phase.start"]
    assert phases[0] == "understand" and "implement" in phases
    ctrl_texts = [e["text"] for e in events if e["type"] == "controller"]
    assert any("baseline" in x for x in ctrl_texts)
    assert any("accepted" in x for x in ctrl_texts)
    # viz sink doesn't perturb the run result
    assert t.orchestration_outcome == "green"


def test_run_green_after_one_diagnose_round():
    suite = _fake_suite([_eval(0, 100), _eval(60, 40), _eval(100, 0)])
    snap, restore, _ = _snap_restore()
    t = run(_CFG, phase_runner=_fake_phase(_CONTRACT), suite_runner=suite,
            snapshot=snap, restore=restore)
    assert t.orchestration_outcome == "green"
    assert t.accepted_rounds == 2          # implement + 1 diagnose


def test_run_stuck_when_no_round_improves():
    suite = _fake_suite([_eval(0, 100), _eval(60, 40),
                         _eval(55, 45), _eval(55, 45),
                         _eval(50, 50), _eval(50, 50)])
    snap, restore, state = _snap_restore()
    t = run(_CFG, phase_runner=_fake_phase(_CONTRACT), suite_runner=suite,
            snapshot=snap, restore=restore)
    assert t.orchestration_outcome == "stuck"
    assert t.reverted_rounds == 2 and t.accepted_rounds == 1
    assert state["restores"] >= 1


def test_run_keeps_agent_work_when_gate_never_accepts():
    """Safety floor: if the regression gate never accepts a round (e.g. a noisy
    suite where the agent's compiling fix doesn't move global pass/fail), finalize
    must NOT revert the worktree to the initial stub snapshot — that reports an
    empty diff for work the agent actually did ("returned a stub"). The agent's
    compiling state is kept as the final on-disk state instead."""
    # stub + every agent attempt compile but show identical 50/50, so decide()
    # sees "no improvement" and accepts nothing.
    suite = _fake_suite([_eval(50, 50)] * 40)
    snaps: list[str] = []
    restores: list[str] = []

    def snapshot():
        tok = f"snap{len(snaps)}"          # snap0 = the initial stub snapshot
        snaps.append(tok)
        return tok

    def restore(tree):
        restores.append(tree)

    t = run(_CFG, phase_runner=_fake_phase(_CONTRACT), suite_runner=suite,
            snapshot=snapshot, restore=restore)

    assert t.accepted_rounds == 0                     # gate accepted nothing
    assert restores, "finalize must restore a kept state"
    assert restores[-1] != "snap0"                    # NOT reverted to the stub
    assert any("agent" in (s.text or "").lower() and "kept" in (s.text or "").lower()
               for s in t.steps if s.kind == StepKind.CONTROLLER)


def test_run_flaky_regression_is_reconfirmed_then_accepted():
    suite = _fake_suite([_eval(0, 100), _eval(60, 40), _eval(58, 42), _eval(100, 0)])
    snap, restore, _ = _snap_restore()
    t = run(_CFG, phase_runner=_fake_phase(_CONTRACT), suite_runner=suite,
            snapshot=snap, restore=restore)
    assert t.orchestration_outcome == "green"
    assert t.accepted_rounds == 2


def test_run_uses_fallback_contract_when_gate_fails():
    suite = _fake_suite([_eval(0, 100), _eval(100, 0)])
    snap, restore, _ = _snap_restore()
    t = run(_CFG, phase_runner=_fake_phase({"understand": ""}), suite_runner=suite,
            snapshot=snap, restore=restore)
    assert t.orchestration_outcome == "green"
    phases = {s.phase for s in t.steps if s.phase}
    assert "understand" in phases and "implement" in phases
    assert any(s.kind == StepKind.CONTROLLER for s in t.steps)


def test_run_caps_huge_contract_to_avoid_argv_overflow():
    """A weak model can emit a huge 'contract'; re-embedding it verbatim into the
    implement prompt overflowed opencode's single-argv limit (Linux E2BIG,
    'Argument list too long'). The orchestrator caps it so prompts stay bounded."""
    huge = "WRAP SPAN indent " + "X" * 500_000     # passes the gate, way over the cap
    prompts: dict[str, str] = {}

    def phase(name, prompt, tools):
        prompts[name] = prompt
        return PhaseOutcome(trace=_trace_with_reads(2),
                            text=huge if name == "understand" else "")

    suite = _fake_suite([_eval(0, 100), _eval(100, 0)])
    snap, restore, _ = _snap_restore()
    run(_CFG, phase_runner=phase, suite_runner=suite, snapshot=snap, restore=restore)
    assert len(prompts["implement"]) < 60_000      # capped, well under MAX_ARG_STRLEN
    assert "truncated" in prompts["implement"]


def test_run_survives_failing_phases():
    """Every phase raising (opencode/docker error, missing binary, …) must NOT
    abort the run — it degrades and still returns a stitched trace, and records
    the failures as controller events."""
    def boom_phase(name, prompt, tools):
        raise RuntimeError(f"{name} boom")

    suite = _fake_suite([_eval(0, 100)] * 30)
    snap, restore, _ = _snap_restore()
    t = run(_CFG, phase_runner=boom_phase, suite_runner=suite, snapshot=snap, restore=restore)
    assert isinstance(t, Trace)                     # did NOT raise
    assert t.orchestration_outcome in ("stuck", "budget", "compile-fail")
    assert any("FAILED" in (s.text or "") for s in t.steps
               if s.kind == StepKind.CONTROLLER)    # degradation is recorded


def test_phased_graph_focuses_diagnose_on_blast_radius():
    """phased+graph: the controller focuses the diagnose loop on failure clusters
    inside the target's blast radius (the injected predicate), recorded as a
    controller event so it's visible + comparable in the trace."""
    in_f = TestFailure(classname="picocli.HelpTest", name="inRadius", kind="failure")
    out_f = TestFailure(classname="picocli.OtherTest", name="outside", kind="error",
                        type="java.lang.NullPointerException")

    def suite():                      # never green → diagnose loop runs
        return SuiteEval(result=_sr(0, 2), failures=[in_f, out_f])

    snap, restore, _ = _snap_restore()
    t = run(_CFG, phase_runner=_fake_phase(_CONTRACT), suite_runner=suite,
            snapshot=snap, restore=restore, in_blast_radius=lambda f: f.name == "inRadius")
    texts = [s.text or "" for s in t.steps if s.kind == StepKind.CONTROLLER]
    assert any("graph: focusing" in x for x in texts)          # graph narrowed the clusters
    assert any("1/2" in x for x in texts)                      # 1 of 2 clusters in radius


def test_phased_runtime_injects_evidence_card_into_diagnose():
    """phased-runtime: an injected read_evidence() supplies a runtime diagnostic
    card that reaches the diagnose prompt and is recorded as a controller event
    (visible + metric-neutral), without changing the outcome."""
    prompts: dict[str, str] = {}

    def phase(name, prompt, tools):
        prompts[name] = prompt
        return PhaseOutcome(_trace_with_reads(2), _CONTRACT.get(name, ""))

    suite = _fake_suite([_eval(0, 100), _eval(60, 40), _eval(100, 0)])  # green after 1 diagnose
    snap, restore, _ = _snap_restore()
    t = run(_CFG, phase_runner=phase, suite_runner=suite, snapshot=snap, restore=restore,
            read_evidence=lambda: "RUNTIME EVIDENCE for TextTable.putValue: args [0,0]")
    assert "RUNTIME EVIDENCE" in prompts["diagnose"]        # card reached the agent
    assert t.orchestration_outcome == "green"
    assert any("runtime evidence" in (s.text or "").lower()
               for s in t.steps if s.kind == StepKind.CONTROLLER)   # recorded


def test_run_without_read_evidence_has_no_card():
    """Plain phased (no read_evidence) → no card text in the diagnose prompt; the
    ablation's only difference is the card."""
    prompts: dict[str, str] = {}

    def phase(name, prompt, tools):
        prompts[name] = prompt
        return PhaseOutcome(_trace_with_reads(2), _CONTRACT.get(name, ""))

    suite = _fake_suite([_eval(0, 100), _eval(60, 40), _eval(100, 0)])
    snap, restore, _ = _snap_restore()
    run(_CFG, phase_runner=phase, suite_runner=suite, snapshot=snap, restore=restore)
    assert "RUNTIME EVIDENCE" not in prompts["diagnose"]


def test_run_survives_failing_suite_snapshot_restore():
    """Infra failures in the injected suite/snapshot/restore must NOT abort the
    run — it finalizes and returns a trace the caller can score."""
    def boom(*_a):
        raise RuntimeError("infra boom")

    t = run(_CFG, phase_runner=_fake_phase(_CONTRACT),
            suite_runner=boom, snapshot=boom, restore=boom)
    assert isinstance(t, Trace)                     # did NOT raise
    assert t.orchestration_outcome == "compile-fail"   # suite never ran → not compiled
