# tests/test_rcc_mgraph_build.py
import json

from abench.rcc_mgraph_build import (artifact_builder, build_mutation_graph,
                                     llm_builder, parse_mgraph_json)


_MG_JSON = {
    "vertices": [
        {"id": "method:p.C.put", "type": "method", "fqn": "p.C.put",
         "is_changed": True, "signature": "Cell(int,int)"},
        {"id": "method:p.C.get", "type": "method", "fqn": "p.C.get"},
        {"id": "test:p.CT.t1", "type": "test", "fqn": "p.CT.t1"},
    ],
    "edges": [
        {"src": "method:p.C.put", "tgt": "method:p.C.get", "type": "CALLS"},
        {"src": "test:p.CT.t1", "tgt": "method:p.C.put", "type": "TEST_ASSERTS"},
    ],
    "target_id": "method:p.C.put",
}

_GT_JSON = {
    "target": {"fqn": "p.C.put", "signature": "Cell(int,int)", "current_body": "SECRET"},
    "method_bodies": {"p.C.get": {"fqn": "p.C.get", "sliced_body": "get(){}"}},
    "chains": [{"id": "c0", "test": {"fqn": "p.CT.t1"},
                "steps": [{"caller_ref": "test", "callee_ref": "target",
                           "call_site": {}, "args": []}]}],
}


def test_parse_mgraph_json_from_prose():
    g = parse_mgraph_json("here:\n" + json.dumps(_MG_JSON) + "\nend")
    assert g.target_fqn == "p.C.put"
    assert set(g.methods()) == {"p.C.put", "p.C.get"}
    assert g.test_fqns == ["p.CT.t1"]


def test_parse_mgraph_json_rejects_garbage():
    assert parse_mgraph_json("no json") is None
    assert parse_mgraph_json('{"vertices": "x", "edges": []}') is None
    assert parse_mgraph_json("") is None


def test_llm_builder_calls_phase_runner_and_parses():
    from abench.orchestrator import PhaseOutcome
    from abench.trace_model import Trace
    calls = []

    def fake_phase(phase, prompt, tools):
        calls.append((phase, tuple(tools)))
        return PhaseOutcome(trace=Trace(), text=json.dumps(_MG_JSON))

    g = llm_builder("/wd", "p.C.put", {"p.C.put": ["p.CT.t1"]}, phase_runner=fake_phase)
    assert g is not None and g.target_fqn == "p.C.put"
    assert calls and calls[0][0] == "build_graph"


def test_llm_builder_returns_none_on_unparseable():
    from abench.orchestrator import PhaseOutcome
    from abench.trace_model import Trace

    def fake_phase(phase, prompt, tools):
        return PhaseOutcome(trace=Trace(), text="sorry, no graph")

    assert llm_builder("/wd", "p.C.put", {}, phase_runner=fake_phase) is None


def test_artifact_builder_loads_and_strips_leak(tmp_path):
    art = tmp_path / "mutation-graph.json"
    art.write_text(json.dumps(_GT_JSON))
    g = artifact_builder("/wd", "p.C.put", {}, artifact_path=art)
    assert g is not None and g.target_fqn == "p.C.put"
    assert "SECRET" not in json.dumps([v.__dict__ for v in g.vertices])  # leak stripped
    assert g.vertex(g.target_id).source is None
    # missing artifact -> None (caller degrades)
    assert artifact_builder("/wd", "p.C.put", {}, artifact_path=tmp_path / "nope.json") is None


def test_build_mutation_graph_dispatches(tmp_path):
    art = tmp_path / "g.json"
    art.write_text(json.dumps(_GT_JSON))
    g = build_mutation_graph("/wd", "p.C.put", {}, builder="artifact", artifact_path=art)
    assert g.target_fqn == "p.C.put"
