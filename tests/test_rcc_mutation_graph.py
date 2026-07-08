# tests/test_rcc_mutation_graph.py
from abench.rcc_mutation_graph import MgEdge, MgVertex, MutationGraph


def _g():
    vs = [
        MgVertex(id="method:p.C.put", type="method", fqn="p.C.put", is_changed=True),
        MgVertex(id="method:p.C.get", type="method", fqn="p.C.get"),
        MgVertex(id="test:p.CT.t1", type="test", fqn="p.CT.t1"),
        MgVertex(id="test:p.DT.t2", type="test", fqn="p.DT.t2"),
    ]
    es = [
        MgEdge(src="test:p.CT.t1", tgt="method:p.C.put", type="CALLS"),
        MgEdge(src="method:p.C.put", tgt="method:p.C.get", type="CALLS"),
        MgEdge(src="test:p.CT.t1", tgt="method:p.C.put", type="TEST_ASSERTS"),
        MgEdge(src="test:p.DT.t2", tgt="method:p.C.put", type="TEST_ASSERTS"),
    ]
    return MutationGraph(target_id="method:p.C.put", vertices=vs, edges=es)


def test_methods_lists_method_vertices_target_first():
    g = _g()
    assert g.methods() == ["p.C.put", "p.C.get"]
    assert g.target_fqn == "p.C.put"


def test_test_classes_and_fqns_derived_from_test_vertices():
    g = _g()
    assert g.test_fqns == ["p.CT.t1", "p.DT.t2"]
    assert g.test_classes == ["p.CT", "p.DT"]
    assert g.classes_total == 2


def test_vertex_lookup_and_edges_of():
    g = _g()
    assert g.vertex("method:p.C.get").fqn == "p.C.get"
    assert g.vertex("nope") is None
    calls_from_put = [e for e in g.edges_from("method:p.C.put") if e.type == "CALLS"]
    assert [e.tgt for e in calls_from_put] == ["method:p.C.get"]


def test_class_cap_keeps_classes_by_test_count():
    g = _g()
    capped = g.with_class_cap(1)
    assert capped.test_classes == ["p.CT"]
    assert capped.classes_total == 2
    assert capped.test_fqns == ["p.CT.t1"]


def test_focus_keeps_target_callers_and_failing_tests():
    vs = [MgVertex(id="method:t", type="method", fqn="p.C.t", is_changed=True),
          MgVertex(id="method:caller", type="method", fqn="p.C.caller"),
          MgVertex(id="method:far", type="method", fqn="p.C.far"),
          MgVertex(id="test:p.T.f", type="test", fqn="p.T.f"),
          MgVertex(id="test:p.T.ok", type="test", fqn="p.T.ok")]
    es = [MgEdge(src="method:caller", tgt="method:t", type="CALLS"),
          MgEdge(src="method:far", tgt="method:caller", type="CALLS"),
          MgEdge(src="test:p.T.f", tgt="method:t", type="TEST_ASSERTS"),
          MgEdge(src="test:p.T.ok", tgt="method:t", type="TEST_ASSERTS")]
    g = MutationGraph(target_id="method:t", vertices=vs, edges=es)
    f = g.focus(failing_tests={"p.T.f"}, k_methods=6)
    assert set(f.methods()) == {"p.C.t", "p.C.caller"}
    assert f.test_fqns == ["p.T.f"]
