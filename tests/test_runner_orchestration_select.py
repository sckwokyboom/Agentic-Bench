from abench.config import Condition
from abench.runner import _select_orchestrator


def _cond(**kw):
    return Condition(name="c", **kw)


def test_engine_defaults_to_python(monkeypatch):
    monkeypatch.delenv("ABENCH_ORCHESTRATOR", raising=False)
    fn = _select_orchestrator(_cond())
    assert fn.__name__ == "run"           # abench.orchestrator.run


def test_env_overrides_condition_engine(monkeypatch):
    monkeypatch.setenv("ABENCH_ORCHESTRATOR", "langgraph")
    import pytest
    pytest.importorskip("langgraph")
    fn = _select_orchestrator(_cond(engine="python"))
    assert fn.__name__ == "run_graph"     # env is the global override


def test_condition_engine_langgraph(monkeypatch):
    monkeypatch.delenv("ABENCH_ORCHESTRATOR", raising=False)
    import pytest
    pytest.importorskip("langgraph")
    fn = _select_orchestrator(_cond(engine="langgraph"))
    assert fn.__name__ == "run_graph"


def test_system_prompt_override_precedence():
    # The runner resolves the effective base as `cond.system_prompt or exp.system_prompt`.
    base = "EXPERIMENT DEFAULT"
    assert (_cond(system_prompt="OVERRIDE").system_prompt or base) == "OVERRIDE"
    assert (_cond().system_prompt or base) == base   # None override → experiment default
