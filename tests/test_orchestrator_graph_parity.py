import pytest

pytest.importorskip("langgraph")  # skip cleanly when the extra isn't installed

from abench.orchestrator import run, OrchestratorConfig, SuiteEval, PhaseOutcome
from abench.orchestrator_graph import run_graph
from abench.metrics import MetricsConfig, extract
from abench.trace_model import StepKind
from abench.failure_report import TestFailure
from abench.regression_gate import SuiteResult
from tests.test_orchestrator import (
    _fake_phase, _fake_suite, _snap_restore, _eval, _CONTRACT, _CFG,
)


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
