# tests/test_rcc_orchestrate.py
import json

import pytest

pytest.importorskip("langgraph")

from abench.orchestrator import OrchestratorConfig, PhaseOutcome, SuiteEval
from abench.rcc_graph import RccConfig
from abench.rcc_orchestrate import run_rcc_condition
from abench.regression_gate import SuiteResult
from abench.trace_model import StepKind, Trace

from tests.test_rcc_graph import (_GAMMA, _SUB, FakeMemory, FakePhase,
                                  _ev, _events, _seq_full, _seq_subset)

_OCFG = OrchestratorConfig(target_label="p.C.put", min_understand_reads=0)
_RCFG = RccConfig(target_label="p.C.put")

_CONTRACT = "The put method must return a non-null Cell and copy the value " \
            "into the table region honoring overflow."


class PrefixPhase(FakePhase):
    """understand returns a contract; alpha/gamma behave like FakePhase."""
    def __call__(self, phase, prompt, tools):
        out = super().__call__(phase, prompt, tools)
        if phase == "understand":
            return PhaseOutcome(trace=Trace(), text=_CONTRACT)
        return out


def _run_cond(subset, full, memory=None, phase=None):
    return run_rcc_condition(
        _OCFG, _RCFG, _SUB,
        phase_runner=phase or PrefixPhase(),
        suite_runner=_seq_full(full),
        subset_runner=_seq_subset(subset),
        memory=memory if memory is not None else FakeMemory(),
        strip_probes=lambda: 0,
    )


def test_green_on_implement_skips_rcc():
    phase = PrefixPhase()
    tr = run_rcc_condition(
        _OCFG, _RCFG, _SUB, phase_runner=phase,
        suite_runner=_seq_full([_ev(0, 2), _ev(100, 0)]),   # baseline red, implement green
        subset_runner=_seq_subset([]), memory=FakeMemory(), strip_probes=lambda: 0)
    assert tr.orchestration_outcome == "green"
    assert [c[0] for c in phase.calls] == ["understand", "implement"]
    ev = "\n".join(_events(tr))
    assert "rcc not invoked" in ev
    assert tr.controller_test_runs == 2


def test_red_implement_hands_off_to_rcc_with_seed():
    phase = PrefixPhase()
    tr = run_rcc_condition(
        _OCFG, _RCFG, _SUB, phase_runner=phase,
        # baseline red, implement still red, fix-1 full green
        suite_runner=_seq_full([_ev(0, 2), _ev(1, 1), _ev(100, 0)]),
        subset_runner=_seq_subset([(_ev(1, 1), ["RCC_PROBE x"]), (_ev(2, 0), [])]),
        memory=FakeMemory(), strip_probes=lambda: 0)
    assert tr.orchestration_outcome == "green"
    assert [c[0] for c in phase.calls] == ["understand", "implement", "alpha",
                                           "beta", "gamma", "fix-1"]
    ev = _events(tr)
    # one continuous trace: prefix events precede rcc events
    i_impl = next(i for i, t in enumerate(ev) if t.startswith("implement done"))
    i_mem = next(i for i, t in enumerate(ev) if t.startswith("memory:"))
    assert i_impl < i_mem
    assert tr.controller_test_runs == 2 + 3      # baseline+implement, beta+subset+full
    assert tr.rcc_root_rank == 1


def test_implement_undercount_forces_full_rerun_and_reaches_rcc():
    # The gradle up-to-date artifact: after the agent ran the suite itself, the
    # controller's post-implement run under-executes (3 of ~105 baseline) and
    # reports 0 failed — a FALSE green that would skip rcc. The guard forces one
    # authoritative full re-run, which reveals real failures, so rcc engages.
    phase = PrefixPhase()
    tr = run_rcc_condition(
        _OCFG, _RCFG, _SUB, phase_runner=phase,
        # baseline full (105), implement under-executed green (3/0), fix-1 full green
        suite_runner=_seq_full([_ev(100, 5), _ev(3, 0), _ev(100, 0)]),
        full_suite_runner=_seq_full([_ev(103, 2)]),   # authoritative: 2 real failures
        subset_runner=_seq_subset([(_ev(1, 1), ["RCC_PROBE x"]), (_ev(2, 0), [])]),
        memory=FakeMemory(), strip_probes=lambda: 0)
    ev = "\n".join(_events(tr))
    assert "under-executed" in ev and "full re-run" in ev
    # rcc engaged (NOT skipped) because the authoritative run was red
    assert [c[0] for c in phase.calls] == ["understand", "implement", "alpha",
                                           "beta", "gamma", "fix-1"]
    assert tr.orchestration_outcome == "green"


def test_no_undercount_keeps_green_and_skips_rcc():
    # implement executes ~all of baseline and is green → the guard does NOT fire
    # (no forced re-run) and rcc stays skipped.
    phase = PrefixPhase()
    full_calls = []

    def full_runner():
        full_calls.append(1)
        return _ev(105, 0)

    tr = run_rcc_condition(
        _OCFG, _RCFG, _SUB, phase_runner=phase,
        suite_runner=_seq_full([_ev(100, 5), _ev(105, 0)]),   # implement full + green
        full_suite_runner=full_runner,
        subset_runner=_seq_subset([]), memory=FakeMemory(), strip_probes=lambda: 0)
    assert tr.orchestration_outcome == "green"
    assert "rcc not invoked" in "\n".join(_events(tr))
    assert full_calls == []            # no undercount → no forced authoritative run


def test_contract_fallback_still_reaches_rcc():
    phase = FakePhase()                           # understand returns "" -> fallback
    tr = run_rcc_condition(
        _OCFG, _RCFG, _SUB, phase_runner=phase,
        suite_runner=_seq_full([_ev(0, 2), _ev(1, 1), _ev(100, 0)]),
        subset_runner=_seq_subset([(_ev(1, 1), []), (_ev(2, 0), [])]),
        memory=FakeMemory(), strip_probes=lambda: 0)
    assert tr.orchestration_outcome == "green"
    assert "fallback" in "\n".join(_events(tr))


def test_focus_narrows_graph_to_failing_tests():
    # A graph with two tests where only one fails: the driver must focus the
    # mutation graph to the failing test before handing off to run_rcc.
    from abench.rcc_mutation_graph import MgEdge, MgVertex, MutationGraph
    from abench.failure_report import TestFailure
    big = MutationGraph(
        target_id="method:p.C.put",
        vertices=[MgVertex(id="method:p.C.put", type="method", fqn="p.C.put",
                           is_changed=True, source="Cell put(){ return null; }"),
                  MgVertex(id="test:p.CT.fail", type="test", fqn="p.CT.fail"),
                  MgVertex(id="test:p.DT.pass", type="test", fqn="p.DT.pass")],
        edges=[MgEdge(src="test:p.CT.fail", tgt="method:p.C.put", type="TEST_ASSERTS"),
               MgEdge(src="test:p.DT.pass", tgt="method:p.C.put", type="TEST_ASSERTS")])
    seen = {}

    class CapturePhase(PrefixPhase):
        def __call__(self, phase, prompt, tools):
            if phase == "alpha":
                seen["alpha"] = prompt
            return super().__call__(phase, prompt, tools)

    red = SuiteEval(result=SuiteResult(compiled=True, ran=True, executed=2,
                                       passed=1, failed=1),
                    failures=[TestFailure(classname="p.CT", name="fail",
                                          kind="failure")])
    run_rcc_condition(
        _OCFG, _RCFG, big, phase_runner=CapturePhase(),
        suite_runner=_seq_full([_ev(0, 2), red, _ev(100, 0)]),
        subset_runner=_seq_subset([(_ev(1, 1), ["RCC_PROBE x"]), (_ev(2, 0), [])]),
        memory=FakeMemory(), strip_probes=lambda: 0)
    # the failing test is in the alpha prompt; the passing one is filtered out
    assert "p.CT.fail" in seen["alpha"]
    assert "p.DT.pass" not in seen["alpha"]


def test_bookkeeping_suite_is_split_out_of_the_arm_cost():
    # The pre-edit baseline suite exists only to record a starting point; the
    # autonomous baseline arm never pays for it. Billing it to the treatment makes
    # rcc look more expensive than its own work — so it must be separately
    # attributed, not folded into one controller total.
    tr = run_rcc_condition(
        _OCFG, _RCFG, _SUB, phase_runner=PrefixPhase(),
        suite_runner=_seq_full([_ev(0, 2), _ev(100, 0)]),   # baseline red, implement green
        subset_runner=_seq_subset([]), memory=FakeMemory(), strip_probes=lambda: 0)
    assert tr.orchestration_outcome == "green"
    assert tr.controller_test_runs == 2                  # baseline + post-implement
    assert tr.controller_bookkeeping_runs == 1           # only the pre-edit one
    assert tr.controller_bookkeeping_s is not None
    assert tr.controller_test_time_s is not None
    # Bookkeeping is a SUBSET of the controller's total suite time, never more.
    assert 0 <= tr.controller_bookkeeping_s <= tr.controller_test_time_s + 1e-6


def test_bookkeeping_split_survives_into_the_rcc_loop():
    # The red path hands off to run_rcc via RccSeed; the split must arrive with it,
    # otherwise every run that actually engages the loop loses the attribution.
    tr = _run_cond([(_ev(1, 1), ["RCC_PROBE x"]), (_ev(2, 0), [])],
                   [_ev(0, 2), _ev(1, 1), _ev(100, 0)])
    assert tr.controller_bookkeeping_runs == 1
    assert tr.controller_bookkeeping_s is not None
    assert tr.controller_test_runs >= 2
