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


def test_contract_fallback_still_reaches_rcc():
    phase = FakePhase()                           # understand returns "" -> fallback
    tr = run_rcc_condition(
        _OCFG, _RCFG, _SUB, phase_runner=phase,
        suite_runner=_seq_full([_ev(0, 2), _ev(1, 1), _ev(100, 0)]),
        subset_runner=_seq_subset([(_ev(1, 1), []), (_ev(2, 0), [])]),
        memory=FakeMemory(), strip_probes=lambda: 0)
    assert tr.orchestration_outcome == "green"
    assert "fallback" in "\n".join(_events(tr))
