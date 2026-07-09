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
                         stats={"chain_count": 3, "distinct_tests": 3},
                         change_origin={"kind": "method_level_only", "method_fqn": "C.put",
                                        "changed_statement_available": False})


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


def test_score_chains_prioritizes_failed_and_short():
    from abench.rcc_graph_layers import score_chains
    g = annotate_status(_g(), failed_ids={"T.a"})
    scored = score_chains(g)
    by_id = {s["path_id"]: s for s in scored}
    # failed path scores higher than an unknown one of equal length
    assert by_id["p1"]["score"] > by_id["p2"]["score"]
    assert "leads_to_failed_test" in by_id["p1"]["selection_reason"]
    # shorter path (p1 len2) beats a longer unknown path (p3 len3)
    assert by_id["p1"]["score"] > by_id["p3"]["score"]


def test_build_subgraph_keeps_all_failed_and_reports_drops():
    from abench.rcc_graph_layers import build_subgraph
    g = annotate_status(_g(), failed_ids={"T.a"})
    gs = build_subgraph(g, k_failed=10, k_passing=2, k_unknown=1)
    assert gs["target"] == "C.put"
    assert set(gs["methods"]) >= {"C.put", "C.caller"}   # target + direct caller
    assert gs["test_frontier"]["failed"] == ["T.a"]      # ALL failed ids
    # dropped counts reported (we asked for 1 unknown of 2)
    assert gs["dropped_counts"]["unknown_reachable"] >= 1
    # every selected path carries a reason
    assert all(p["selection_reason"] for p in gs["paths"])


def test_render_slice_has_stats_frontier_and_omission():
    from abench.rcc_graph_layers import build_index, build_subgraph, render_slice
    g = annotate_status(_g(), failed_ids={"T.a"})
    slice_ = render_slice(g, build_subgraph(g), build_index(g))
    assert slice_["source_graph_stats"]["chain_count"] == 3
    assert slice_["test_frontier"]["failed"] == ["T.a"]
    assert slice_["omission_note"]                       # non-empty honesty note
    assert slice_["change_origin"]["kind"] == "method_level_only"
    # edges are typed objects with both directions, never strings
    e = slice_["edges"][0]
    assert set(e) >= {"from", "to", "type", "structural_direction", "influence_direction"}


def test_persist_writes_four_layers(tmp_path):
    from abench.rcc_graph_layers import build_index, build_subgraph, persist, render_slice
    g = annotate_status(_g(), failed_ids={"T.a"})
    idx, gs = build_index(g), build_subgraph(g)
    sl = render_slice(g, gs, idx)
    persist(tmp_path, g, idx, gs, sl)
    import json as _j
    for name in ("raw", "index", "subgraph", "slice"):
        assert (tmp_path / f"{name}.json").is_file()
    raw = _j.loads((tmp_path / "raw.json").read_text())
    assert raw["stats"]["chain_count"] == 3 and "SECRET" not in _j.dumps(raw)


def test_subgraph_frontier_dedups_and_honors_failed_ids():
    from abench.rcc_graph_layers import build_subgraph
    g = _g()  # NOT annotated — failed_ids param must still yield the failed frontier
    gs = build_subgraph(g, failed_ids={"T.a"}, k_unknown=5)
    assert "T.a" in gs["test_frontier"]["failed"]
    # samples carry no duplicate test fqns
    us = gs["test_frontier"]["unknown_reachable_sample"]
    assert len(us) == len(set(us))
