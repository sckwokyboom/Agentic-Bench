from abench.rcc_graph_layers import annotate_status, build_index
from abench.rcc_mutation_graph import MgChain, MgEdge, MgVertex, MutationGraph


def _g():
    vs = [MgVertex(id="method:C.put", type="method", fqn="C.put", is_changed=True),
          MgVertex(id="method:C.caller", type="method", fqn="C.caller"),
          MgVertex(id="test:T.a", type="test", fqn="T.a"),
          MgVertex(id="test:T.b", type="test", fqn="T.b"),
          MgVertex(id="test:U.c", type="test", fqn="U.c")]
    es = [MgEdge(src="method:C.caller", tgt="method:C.put", type="CALLS"),
          MgEdge(src="test:T.a", tgt="method:C.put", type="TEST_ASSERTS"),
          MgEdge(src="test:T.b", tgt="method:C.put", type="TEST_ASSERTS"),
          MgEdge(src="test:U.c", tgt="method:C.caller", type="TEST_ASSERTS")]
    ch = [MgChain(id="p1", test_fqn="T.a", node_ids=["test:T.a", "method:C.put"]),
          MgChain(id="p2", test_fqn="T.b", node_ids=["test:T.b", "method:C.put"]),
          MgChain(id="p3", test_fqn="U.c", node_ids=["test:U.c", "method:C.caller",
                                                     "method:C.put"])]
    return MutationGraph(target_id="method:C.put", vertices=vs, edges=es, chains=ch,
                         stats={"chain_count": 3, "distinct_tests": 3})


def test_annotate_status_marks_failed_else_unknown_reachable():
    g = annotate_status(_g(), failed_ids={"T.a"})
    assert g.vertex("test:T.a").status == "failed"
    assert g.vertex("test:T.b").status == "unknown_reachable"
    assert g.vertex("test:U.c").status == "unknown_reachable"
    # chains mirror their test's status
    assert next(c for c in g.chains if c.id == "p1").status == "failed"
    assert next(c for c in g.chains if c.id == "p2").status == "unknown_reachable"


def test_annotate_status_with_passing_ids():
    g = annotate_status(_g(), failed_ids={"T.a"}, passing_ids={"T.b"})
    assert g.vertex("test:T.b").status == "passing"
    assert g.vertex("test:U.c").status == "unknown_reachable"


def test_build_index_summary():
    g = annotate_status(_g(), failed_ids={"T.a"})
    idx = build_index(g)
    assert idx["method_count"] == 2 and idx["test_count"] == 3
    assert idx["chain_count"] == 3
    assert idx["status_counts"] == {"failed": 1, "passing": 0, "unknown_reachable": 2}
    # top callers ranked by chains through them; addRowValues-style caller present
    assert idx["top_callers"][0]["method"] == "C.caller"
    assert idx["edge_type_counts"]["TEST_ASSERTS"] == 3
    assert set(idx["reachable_test_classes"]) == {"T", "U"}
