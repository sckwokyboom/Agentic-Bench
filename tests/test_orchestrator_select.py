from abench.runner import _select_orchestrator


def test_select_defaults_to_python(monkeypatch):
    monkeypatch.delenv("ABENCH_ORCHESTRATOR", raising=False)
    from abench.orchestrator import run as py
    assert _select_orchestrator() is py


def test_select_langgraph_when_env_set(monkeypatch):
    monkeypatch.setenv("ABENCH_ORCHESTRATOR", "langgraph")
    from abench.orchestrator_graph import run_graph
    assert _select_orchestrator() is run_graph
