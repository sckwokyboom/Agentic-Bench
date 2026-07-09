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
    # cluster medoids carry no duplicate path ids
    cl = gs["test_frontier"]["unknown_reachable_clusters"]
    medoids = [c["medoid_path_id"] for c in cl]
    assert len(medoids) == len(set(medoids))


def test_build_subgraph_uses_clusters_and_keeps_all_failed():
    from abench.rcc_graph_layers import annotate_status, build_subgraph
    from abench.rcc_mutation_graph import MgChain, MgEdge, MgVertex, MutationGraph
    vs = [MgVertex(id="method:C.put", type="method", fqn="C.put", is_changed=True),
          MgVertex(id="method:C.addRow", type="method", fqn="C.addRow"),
          MgVertex(id="method:H.syn", type="method", fqn="H.syn")]
    for t in ("HT.f1", "HT.u1", "HT.u2", "HT.u3", "TT.u4"):
        vs.append(MgVertex(id=f"test:{t}", type="test", fqn=f"picocli.{t}"))
    es = [MgEdge(src="method:C.addRow", tgt="method:C.put", type="CALLS")]
    chains = [MgChain(id="p0", test_fqn="picocli.HT.f1",
                      node_ids=["test:HT.f1", "method:C.addRow", "method:C.put"])]
    for i, t in enumerate(("HT.u1", "HT.u2", "HT.u3", "TT.u4"), 1):
        seq = (["test:" + t, "method:C.addRow", "method:C.put"] if i < 3
               else ["test:" + t, "method:H.syn", "method:C.addRow", "method:C.put"])
        chains.append(MgChain(id=f"p{i}", test_fqn=f"picocli.{t}", node_ids=seq))
    g = MutationGraph(target_id="method:C.put", vertices=vs, edges=es, chains=chains)
    annotate_status(g, failed_ids={"picocli.HT.f1"})
    gs = build_subgraph(g, failed_ids={"picocli.HT.f1"}, k_unknown=2)
    assert gs["test_frontier"]["failed"] == ["picocli.HT.f1"]     # all failed kept
    assert "unknown_reachable_clusters" in gs["test_frontier"]     # clusters, not flat sample
    cl = gs["test_frontier"]["unknown_reachable_clusters"]
    assert len(cl) >= 2 and all("path_shape" in c and "medoid_test" in c for c in cl)
    assert gs["selection_method"] == "path_k_medoids_weighted_lcs"


def test_render_slice_edges_sample_path_ids_not_full():
    from abench.rcc_graph_layers import (annotate_status, build_index, build_subgraph,
                                         render_slice)
    from abench.rcc_mutation_graph import MgChain, MgEdge, MgVertex, MutationGraph
    e = MgEdge(src="test:T.a", tgt="method:C.put", type="TEST_ASSERTS",
               path_ids=[f"p{i}" for i in range(12)])
    g = MutationGraph(
        target_id="method:C.put",
        vertices=[MgVertex(id="method:C.put", type="method", fqn="C.put", is_changed=True),
                  MgVertex(id="test:T.a", type="test", fqn="p.T.a")],
        edges=[e], chains=[MgChain(id="p0", test_fqn="p.T.a",
                                   node_ids=["test:T.a", "method:C.put"])])
    annotate_status(g, failed_ids={"p.T.a"})
    sl = render_slice(g, build_subgraph(g, failed_ids={"p.T.a"}), build_index(g))
    edge = sl["edges"][0]
    assert "path_ids" not in edge                        # full array gone
    assert edge["path_count"] == 12 and len(edge["sample_path_ids"]) <= 5
    assert edge["omitted_path_ids_count"] == 12 - len(edge["sample_path_ids"])


def test_build_index_top_callers_distinct_chains_and_topN_classes():
    from abench.rcc_graph_layers import build_index
    from abench.rcc_mutation_graph import MgChain, MgEdge, MgVertex, MutationGraph
    vs = [MgVertex(id="method:C.put", type="method", fqn="C.put", is_changed=True),
          MgVertex(id="method:C.addRow", type="method", fqn="C.addRow")]
    for t in ("A.t1", "A.t2", "B.t3"):
        vs.append(MgVertex(id=f"test:{t}", type="test", fqn=f"p.{t}"))
    # a chain where addRow appears TWICE — must count the chain ONCE
    chains = [MgChain(id="p1", test_fqn="p.A.t1",
                      node_ids=["test:A.t1", "method:C.addRow", "method:C.addRow",
                                "method:C.put"]),
              MgChain(id="p2", test_fqn="p.A.t2",
                      node_ids=["test:A.t2", "method:C.addRow", "method:C.put"]),
              MgChain(id="p3", test_fqn="p.B.t3", node_ids=["test:B.t3", "method:C.put"])]
    g = MutationGraph(target_id="method:C.put", vertices=vs, edges=[], chains=chains)
    idx = build_index(g)
    tc = {c["method"]: c["distinct_chains"] for c in idx["top_callers"]}
    assert tc["C.addRow"] == 2                       # 2 distinct chains, NOT 3
    assert "reachable_test_classes_top" in idx and "other_reachable_test_classes" in idx


def test_build_subgraph_classifies_focused_vs_path_context():
    from abench.rcc_graph_layers import annotate_status, build_subgraph
    from abench.rcc_mutation_graph import MgChain, MgEdge, MgVertex, MutationGraph
    vs = [MgVertex(id="method:C.put", type="method", fqn="C.put", is_changed=True),
          MgVertex(id="method:C.addRow", type="method", fqn="C.addRow"),  # direct caller
          MgVertex(id="method:H.syn", type="method", fqn="H.syn"),        # path context
          MgVertex(id="test:T.f", type="test", fqn="p.T.f")]
    es = [MgEdge(src="method:C.addRow", tgt="method:C.put", type="CALLS")]
    chains = [MgChain(id="p1", test_fqn="p.T.f",
                      node_ids=["test:T.f", "method:H.syn", "method:C.addRow",
                                "method:C.put"])]
    g = MutationGraph(target_id="method:C.put", vertices=vs, edges=es, chains=chains)
    annotate_status(g, failed_ids={"p.T.f"})
    gs = build_subgraph(g, failed_ids={"p.T.f"})
    roles = {m["fqn"]: m["role"] for m in gs["focused_methods"]}
    assert roles == {"C.put": "target", "C.addRow": "direct_caller"}   # syn NOT focused
    assert "H.syn" in gs["path_context_methods"]                        # syn is context


def test_render_prompt_slice_v2_is_compact_and_focused():
    from abench.rcc_graph_layers import (annotate_status, build_index, build_subgraph,
                                         render_prompt_slice)
    from abench.rcc_mgraph_build import artifact_builder
    import json
    g = artifact_builder("/wd", "putValue", {}, artifact_path=(
        "experiments/picocli-putValue/gt-out/slice-work/357b6bd1af378e00.graph.json"))
    if not g:
        import pytest; pytest.skip("gt sample absent")
    f = {"picocli.HelpTest.testTextTablePutValue_NullOrEmpty",
         "picocli.HelpTest.testTextTablePutValue_DisallowsInvalidRowIndex",
         "picocli.TextTableTest.addRowValues"}
    annotate_status(g, failed_ids=f)
    ps = render_prompt_slice(g, build_subgraph(g, failed_ids=f), build_index(g))
    blob = json.dumps(ps)
    # ACCEPTANCE GATE
    assert ps["prompt_slice_stats"]["approx_tokens"] < 5000
    assert ps["schema"] == "rcc.prompt_slice.v2"
    # focused = target + direct callers/callees ONLY (no synopsis/assert noise)
    assert all(m["role"] in ("target", "direct_caller", "direct_callee")
               for m in ps["focused_methods"])
    assert any(m["role"] == "target" for m in ps["focused_methods"])
    assert len(ps["focused_methods"]) <= 4
    # no debug-only fields in the prompt slice (raw member_ids/full histogram keys;
    # NOT the compact sample_member_ids/reachable_test_classes_top the gate requires
    # below — a plain substring check would false-positive on those compact fields)
    assert '"member_ids":' not in blob and '"reachable_test_classes":' not in blob
    # clusters appear exactly once, no member_ids, compressed shapes
    cl = ps["representative_path_clusters"]
    assert cl and all("member_ids" not in c for c in cl)
    assert any("×" in c["path_shape"] for c in cl)          # run-length compression
    assert all("sample_member_ids" in c and c["omitted_member_ids_count"] >= 0 for c in cl)
    # compact edges: collapsed, no full path_ids array
    for e in ps["compact_edges"]:
        assert "path_ids" not in e and "edge_types" in e and len(e["sample_path_ids"]) <= 3
    # top-N index only
    assert len(ps["source_graph_summary"].get("reachable_test_classes_top", [])) <= 5


def test_persist_writes_prompt_slice_separate_from_debug(tmp_path):
    from abench.rcc_graph_layers import (annotate_status, build_index, build_subgraph,
                                         persist, render_prompt_slice, render_slice)
    from abench.rcc_mutation_graph import MgChain, MgEdge, MgVertex, MutationGraph
    import json
    vs = [MgVertex(id="method:C.put", type="method", fqn="C.put", is_changed=True),
          MgVertex(id="test:T.a", type="test", fqn="p.T.a")]
    g = MutationGraph(target_id="method:C.put", vertices=vs,
                      edges=[MgEdge(src="test:T.a", tgt="method:C.put", type="TEST_ASSERTS")],
                      chains=[MgChain(id="p0", test_fqn="p.T.a",
                                      node_ids=["test:T.a", "method:C.put"])])
    annotate_status(g, failed_ids={"p.T.a"})
    idx, gs = build_index(g), build_subgraph(g, failed_ids={"p.T.a"})
    persist(tmp_path, g, idx, gs, render_slice(g, gs, idx),
            prompt_slice=render_prompt_slice(g, gs, idx))
    for name in ("raw", "index", "subgraph", "slice", "clusters", "prompt_slice"):
        assert (tmp_path / f"{name}.json").is_file()
    ps = json.loads((tmp_path / "prompt_slice.json").read_text())
    assert ps["schema"] == "rcc.prompt_slice.v2"


def test_compact_edges_preserves_both_calls_and_data_dep_types():
    # A direct caller with BOTH a CALLS and a DATA_DEP edge into the target must keep
    # both types after the (from,to) collapse in render_prompt_slice's compact_edges —
    # the collapse already unions edge_types; this locks the invariant.
    from abench.rcc_graph_layers import (annotate_status, build_index, build_subgraph,
                                         render_prompt_slice)
    from abench.rcc_mutation_graph import MgChain, MgEdge, MgVertex, MutationGraph
    vs = [MgVertex(id="method:C.put", type="method", fqn="C.put", is_changed=True),
          MgVertex(id="method:C.caller", type="method", fqn="C.caller"),
          MgVertex(id="test:T.a", type="test", fqn="p.T.a")]
    es = [MgEdge(src="method:C.caller", tgt="method:C.put", type="CALLS"),
          MgEdge(src="method:C.caller", tgt="method:C.put", type="DATA_DEP", data_var="v"),
          MgEdge(src="test:T.a", tgt="method:C.put", type="TEST_ASSERTS")]
    chains = [MgChain(id="p0", test_fqn="p.T.a",
                      node_ids=["test:T.a", "method:C.caller", "method:C.put"])]
    g = MutationGraph(target_id="method:C.put", vertices=vs, edges=es, chains=chains)
    annotate_status(g, failed_ids={"p.T.a"})
    ps = render_prompt_slice(g, build_subgraph(g, failed_ids={"p.T.a"}), build_index(g))
    e = next(e for e in ps["compact_edges"]
            if e["from"] == "method:C.caller" and e["to"] == "method:C.put")
    assert set(e["edge_types"]) == {"CALLS", "DATA_DEP"}


def test_render_prompt_slice_v2_failed_test_links_and_gamma_grounding():
    from abench.rcc_graph_layers import (annotate_status, build_index, build_subgraph,
                                         render_prompt_slice)
    from abench.rcc_mgraph_build import artifact_builder
    from abench.rcc_prompts import gamma_prompt
    g = artifact_builder("/wd", "putValue", {}, artifact_path=(
        "experiments/picocli-putValue/gt-out/slice-work/357b6bd1af378e00.graph.json"))
    if not g:
        import pytest; pytest.skip("gt sample absent")
    f = {"picocli.HelpTest.testTextTablePutValue_NullOrEmpty",
         "picocli.HelpTest.testTextTablePutValue_DisallowsInvalidRowIndex",
         "picocli.TextTableTest.addRowValues"}
    annotate_status(g, failed_ids=f)
    ps = render_prompt_slice(g, build_subgraph(g, failed_ids=f), build_index(g))
    links = ps.get("failed_test_links", [])
    assert len(links) == 3
    for link in links:
        assert {"test", "observes", "path_shape", "relations"} <= set(link)
        assert link["observes"] == ps["target"]
    gp = gamma_prompt(ps, "SPECS", [])
    assert "FAILED-TEST GROUNDING" in gp


def test_focused_method_truncated_source_gets_note():
    from abench.rcc_graph_layers import (annotate_status, build_index, build_subgraph,
                                         render_prompt_slice)
    from abench.rcc_mgraph_build import artifact_builder
    g = artifact_builder("/wd", "putValue", {}, artifact_path=(
        "experiments/picocli-putValue/gt-out/slice-work/357b6bd1af378e00.graph.json"))
    if not g:
        import pytest; pytest.skip("gt sample absent")
    f = {"picocli.HelpTest.testTextTablePutValue_NullOrEmpty",
         "picocli.HelpTest.testTextTablePutValue_DisallowsInvalidRowIndex",
         "picocli.TextTableTest.addRowValues"}
    annotate_status(g, failed_ids=f)
    ps = render_prompt_slice(g, build_subgraph(g, failed_ids=f), build_index(g))
    m = next(m for m in ps["focused_methods"] if m["role"] == "direct_caller")
    assert m.get("source_note") == "(excerpt — read the full body from the workdir if needed)"


def test_focused_keeps_late_named_direct_caller_despite_context_noise():
    # A direct caller that sorts AFTER many path-context methods must NOT be
    # crowded out of focused_methods by the k_methods cap (R3.1 review bug).
    from abench.rcc_graph_layers import annotate_status, build_subgraph
    from abench.rcc_mutation_graph import MgChain, MgEdge, MgVertex, MutationGraph
    vs = [MgVertex(id="method:C.put", type="method", fqn="C.put", is_changed=True),
          MgVertex(id="method:C.zzzCaller", type="method", fqn="C.zzzCaller"),
          MgVertex(id="test:T.f", type="test", fqn="p.T.f")]
    es = [MgEdge(src="method:C.zzzCaller", tgt="method:C.put", type="CALLS")]
    nodes = ["test:T.f"]
    for i in range(10):  # 10 early-named path-context methods on the chain
        vs.append(MgVertex(id=f"method:A.ctx{i}", type="method", fqn=f"A.ctx{i}"))
        nodes.append(f"method:A.ctx{i}")
    nodes += ["method:C.zzzCaller", "method:C.put"]
    chains = [MgChain(id="p1", test_fqn="p.T.f", node_ids=nodes)]
    g = MutationGraph(target_id="method:C.put", vertices=vs, edges=es, chains=chains)
    annotate_status(g, failed_ids={"p.T.f"})
    gs = build_subgraph(g, failed_ids={"p.T.f"}, k_methods=8)
    roles = {m["fqn"]: m["role"] for m in gs["focused_methods"]}
    assert roles == {"C.put": "target", "C.zzzCaller": "direct_caller"}   # caller kept
    assert "A.ctx0" in gs["path_context_methods"]
