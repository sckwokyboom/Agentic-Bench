# tests/test_rcc_prompts.py
import json

from abench.rcc_graph_layers import (
    annotate_status, build_index, build_subgraph, render_prompt_slice,
)
from abench.rcc_mutation_graph import MgEdge, MgVertex, MutationGraph
from abench.rcc_prompts import (GAMMA_FORMAT_REMINDER, PROBE_MARKER, PROBE_PREFIX,
                                alpha_prompt, beta_prompt, beta_repair_prompt,
                                cache_fix_prompt, causal_rank, fix_prompt,
                                gamma_prompt, parse_causal_delta, root_rank)


def _g():
    vs = [MgVertex(id="method:p.C.put", type="method", fqn="p.C.put", is_changed=True,
                   l1_skeleton={"signature": "Cell(int,int,Text)"},
                   source="Cell put(int r,int c,Text v){ return null; }"),
          MgVertex(id="method:p.C.get", type="method", fqn="p.C.get",
                   source="Object get(){...}"),
          MgVertex(id="test:p.CT.t1", type="test", fqn="p.CT.t1", source="assertX()")]
    es = [MgEdge(src="method:p.C.put", tgt="method:p.C.get", type="CALLS",
                 call_site={"file": "C.java", "line": 31, "code": "get()"}),
          MgEdge(src="method:p.C.put", tgt="method:p.C.get", type="DATA_DEP",
                 data_var="value"),
          MgEdge(src="test:p.CT.t1", tgt="method:p.C.put", type="TEST_ASSERTS")]
    return MutationGraph(target_id="method:p.C.put", vertices=vs, edges=es)


def _slice():
    g = annotate_status(_g(), failed_ids=set())
    idx = build_index(g)
    sub = build_subgraph(g)
    return render_prompt_slice(g, sub, idx)


def test_alpha_covers_vertices_and_edges():
    a = alpha_prompt(_slice())
    assert "p.C.put" in a and "return null" in a           # target source shown
    assert "p.C.get" in a                                   # direct callee focused
    assert "CALLS" in a and "DATA_DEP" in a                 # collapsed edge types present
    assert "edge" in a.lower() and "pre" in a               # asks for edge + vertex specs


def test_beta_prompt_targets_graph_methods():
    sl = _slice()
    b = beta_prompt(sl, "SPECS")
    assert PROBE_PREFIX in b and PROBE_MARKER in b and "SPECS" in b
    assert "p.C.put" in b
    assert PROBE_MARKER in beta_repair_prompt(sl)


_CDG = {
    "vertices": [
        {"id": "cd1", "mutation_vertex": "method:p.C.put", "type": "root_cause",
         "spec_text": "put must return non-null", "violated": True,
         "is_root_cause": True, "confidence": 0.96, "runtime_value": "ret=null"},
        {"id": "cd2", "mutation_vertex": "method:p.C.get", "type": "downstream_effect",
         "violated": True, "is_root_cause": False, "confidence": 0.9},
    ],
    "edges": [{"from": "cd1", "to": "cd2", "type": "CAUSES",
               "path": ["method:p.C.put", "method:p.C.get"], "reasoning": "null propagates"}],
}


def test_gamma_prompt_asks_for_causal_delta_schema():
    sl = _slice()
    p = gamma_prompt(sl, "SPECS", ["RCC_PROBE put: ret=null"])
    assert "CausalDeltaSubGraph" in p or "is_root_cause" in p
    assert "ret=null" in p and "mutation_vertex" in p
    assert "no runtime logs" in gamma_prompt(sl, "S", [])


def test_parse_causal_delta_from_prose_and_reject_garbage():
    assert parse_causal_delta("x " + json.dumps(_CDG) + " y")["vertices"][0]["confidence"] == 0.96
    assert parse_causal_delta("nope") is None
    assert parse_causal_delta('{"vertices": 1, "edges": []}') is None


def test_causal_rank_by_root_cause_then_confidence():
    g = _g()
    ranks = causal_rank(_CDG, g.methods())
    assert ranks[0][0] == "p.C.put"                    # is_root_cause wins
    assert root_rank(ranks, "p.C.put") == 1
    # degraded (no graph) keeps mutation-graph order (target first)
    assert causal_rank(None, g.methods())[0][0] == "p.C.put"


def test_fix_prompt_and_cache_fix_carry_the_delta():
    g = _g()
    f = fix_prompt("the put method", "p.C.put", _CDG, "SPECS", [], "p.C.put", 1)
    assert "root" in f.lower() and "CAUSES" in f
    c = cache_fix_prompt("the put method", _CDG, [])
    assert "previous successful" in c and "is_root_cause" in c


_SLICE = {
    "schema": "rcc.prompt_slice.v2",
    "target": "p.C.put",
    "change_origin": {"kind": "method_level_only", "method_fqn": "p.C.put",
                      "changed_statement_available": False},
    "source_graph_summary": {
        "methods": 90, "tests": 1406, "chains": 1526, "edges": 3375,
        "status": {"failed": 3, "passing": 0, "unknown_reachable": 1403},
        "reachable_test_classes_top": [{"class": "p.HT", "tests": 1200}],
        "other_reachable_test_classes": 4,
        "top_callers": [{"method": "p.C.addRowValues", "distinct_chains": 1256}]},
    "selection_summary": {"method": "path_k_medoids_weighted_lcs",
                          "shown_failed_tests": 1, "shown_unknown_clusters": 1,
                          "shown_focused_methods": 2,
                          "dropped": {"unknown_reachable": 1400}},
    "focused_methods": [
        {"fqn": "p.C.put", "role": "target", "signature": "Cell(int,int,Text)",
         "source": None, "source_from_workdir": True},
        {"fqn": "p.C.addRowValues", "role": "direct_caller",
         "signature": "void(Text[])", "source": "void addRowValues(){...}",
         "source_from_workdir": False}],
    "path_context_methods": ["p.H.synopsis"],
    "failed_tests": ["p.HT.tPut"],
    "representative_path_clusters": [
        {"cluster_id": "unknown_reachable_0", "size": 3,
         "medoid_test": "p.HT.tOther",
         "path_shape": "test:p.HT → addRowValues×2 → put",
         "nearest_examples": [], "sample_member_ids": ["p2"],
         "omitted_member_ids_count": 2}],
    "compact_edges": [
        {"from": "method:p.C.addRowValues", "to": "method:p.C.put",
         "edge_types": ["CALLS", "DATA_DEP"],
         "structural_direction": "caller_to_callee",
         "influence_direction": "callee_to_caller", "path_count": 2,
         "sample_path_ids": ["p2"], "omitted_path_ids_count": 1}],
    "omission_note": ("RANKED SLICE of a 90-method / 1406-test / 1526-chain graph. "
                      "focused_methods are the ONLY contract subjects (target + "
                      "direct callers/callees); path_context_methods and the path "
                      "clusters are STRUCTURAL REFERENCE — do NOT write contracts "
                      "for them. Omitted tests/paths are not necessarily irrelevant. "
                      "Influence flows method→test (reverse of the call direction)."),
    "prompt_slice_stats": {"chars": 1200, "approx_tokens": 300, "focused_methods": 2,
                          "edges": 1, "clusters": 1},
}


def test_alpha_over_slice_has_stats_and_omission():
    a = alpha_prompt(_SLICE)
    assert "p.C.put" in a and "addRowValues" in a
    assert "1526" in a and "RANKED SLICE" in a           # full-graph stats + honesty
    assert "CALLS" in a and "pre" in a and "edge" in a.lower()
    assert "CLUSTERS" in a and "put" in a and "→" in a   # representative path clusters


def test_gamma_over_slice_has_frontier_and_influence():
    g = gamma_prompt(_SLICE, "SPECS", ["RCC_PROBE put: ret=null"])
    assert "ret=null" in g and "mutation_vertex" in g
    assert "influence" in g.lower()                      # method->test direction cue
    assert "p.HT.tPut" in g                              # failed frontier present
    assert "dropped" in g.lower() or "omitted" in g.lower()
    assert "CLUSTERS" in g and "→" in g                   # representative path clusters


def test_beta_carries_failed_test_grounding():
    b = beta_prompt(_slice(), "SPECS")
    assert "FAILED-TEST GROUNDING" in b and "probe what these failing tests observe" in b


# ── Phase IV prompts (enrich contracts + extend causal graph) ────────────────

def test_alpha_enrich_prompt_grounds_in_still_failing_tests():
    from abench.rcc_prompts import alpha_enrich_prompt
    p = alpha_enrich_prompt(_SLICE, "PRIOR CONTRACT TEXT",
                            ["picocli.HelpTest.testWrap", "picocli.TextTableTest.addRowValues"])
    assert "SECOND PASS" in p and "STILL" in p                 # deep-pass framing
    assert "picocli.HelpTest.testWrap" in p                    # the still-failing tests
    assert "PRIOR CONTRACT TEXT" in p                          # refines, not restarts
    assert "Do NOT edit code" in p


def test_gamma_extend_prompt_carries_prior_graph_and_schema():
    from abench.rcc_prompts import gamma_extend_prompt
    prior = {"vertices": [{"id": "cd1", "mutation_vertex": "method:p.C.put",
                           "is_root_cause": True}], "edges": []}
    p = gamma_extend_prompt(_SLICE, "REFINED SPECS", ["RCC_PROBE put: ret=null"], prior)
    assert "EXTEND" in p and "do NOT discard" in p             # extend, not replace
    assert "PRIOR CAUSAL GRAPH" in p and "cd1" in p            # prior graph embedded
    assert "root_cause|downstream_effect" in p                 # same CDG JSON schema
    assert "RCC_PROBE put: ret=null" in p                      # new probe logs
    assert "(no prior graph)" in gamma_extend_prompt(_SLICE, "S", [], None)
