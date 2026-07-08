# tests/test_rcc_prompts.py
import json

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


def test_alpha_covers_vertices_and_edges():
    a = alpha_prompt(_g())
    assert "p.C.put" in a and "return null" in a           # vertex source shown
    assert "CALLS" in a and "get()" in a                    # edge with call_site
    assert "DATA_DEP" in a and "value" in a                 # dataflow edge
    assert "edge" in a.lower() and "pre" in a               # asks for edge + vertex specs


def test_beta_prompt_targets_graph_methods():
    b = beta_prompt(_g(), "SPECS")
    assert PROBE_PREFIX in b and PROBE_MARKER in b and "SPECS" in b
    assert "p.C.put" in b
    assert PROBE_MARKER in beta_repair_prompt(_g())


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
    g = _g()
    p = gamma_prompt(g, "SPECS", ["RCC_PROBE put: ret=null"])
    assert "CausalDeltaSubGraph" in p or "is_root_cause" in p
    assert "ret=null" in p and "mutation_vertex" in p
    assert "no runtime logs" in gamma_prompt(g, "S", [])


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
