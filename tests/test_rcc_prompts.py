# tests/test_rcc_prompts.py
import json

from abench.rcc_prompts import (
    GAMMA_FORMAT_REMINDER, PROBE_MARKER, PROBE_PREFIX, alpha_prompt, beta_prompt,
    beta_repair_prompt, cache_fix_prompt, causal_rank, fix_prompt, gamma_prompt,
    parse_gamma, root_rank,
)
from abench.rcc_subgraph import RccSubgraph

_SUB = RccSubgraph(
    target_fqn="p.C.putValue",
    methods=["p.C.putValue", "p.C.getValue"],
    test_fqns=["p.CT.t1"], test_classes=["p.CT"],
    sources={"p.C.putValue": "public Object putValue() { return null; }"},
)

_GRAPH = {
    "nodes": [{"id": "p.C.putValue", "type": "method"},
              {"id": "spec_put", "type": "spec", "method": "p.C.putValue"},
              {"id": "p.C.getValue", "type": "method"}],
    "edges": [
        {"src": "spec_put", "tgt": "p.C.getValue", "type": "causal", "weight": 0.9},
        {"src": "p.C.putValue", "tgt": "p.C.getValue", "type": "causal", "weight": 1.0},
        {"src": "p.C.putValue", "tgt": "p.C.getValue", "type": "calls", "weight": 1.0},
        {"src": "p.C.getValue", "tgt": "p.C.putValue", "type": "causal", "weight": "bad"},
    ],
}


def test_parse_gamma_accepts_json_embedded_in_prose():
    text = "Here is the graph:\n" + json.dumps(_GRAPH) + "\nDone."
    assert parse_gamma(text)["edges"][0]["weight"] == 0.9


def test_parse_gamma_rejects_garbage_and_wrong_shape():
    assert parse_gamma("no json at all") is None
    assert parse_gamma('{"nodes": "not-a-list", "edges": []}') is None
    assert parse_gamma("") is None
    assert parse_gamma(None) is None


def test_causal_rank_sums_causal_weights_via_node_method_attribution():
    ranks = causal_rank(_GRAPH, _SUB.methods)
    # putValue: 0.9 (spec node attributed to it) + 1.0 direct = 1.9
    # getValue: the malformed weight falls back to 0.5; 'calls' edges don't count
    assert ranks == [("p.C.putValue", 1.9), ("p.C.getValue", 0.5)]
    assert root_rank(ranks, "p.C.putValue") == 1
    assert root_rank(ranks, "p.C.nope") is None


def test_causal_rank_empty_graph_keeps_subgraph_order():
    ranks = causal_rank({"nodes": [], "edges": []}, _SUB.methods)
    assert ranks == [("p.C.putValue", 0.0), ("p.C.getValue", 0.0)]


def test_prompts_carry_the_contract_pieces():
    a = alpha_prompt(_SUB)
    assert "p.C.putValue" in a and "return null" in a and "pre" in a
    b = beta_prompt(_SUB, "SPECS-TEXT")
    assert PROBE_PREFIX in b and PROBE_MARKER in b and "SPECS-TEXT" in b
    assert PROBE_MARKER in beta_repair_prompt(_SUB)
    g = gamma_prompt(_SUB, "SPECS-TEXT", ["RCC_PROBE C.putValue: ret=null"])
    assert "ret=null" in g and '"causal"' in g and "p.C.getValue" in g
    g2 = gamma_prompt(_SUB, "S", [])
    assert "no runtime logs" in g2
    f = fix_prompt("the target", "p.C.putValue", _GRAPH, "SPECS", [],
                   "p.C.putValue", attempt=1)
    assert "root" in f.lower() and "CAUSAL GRAPH" in f
    f2 = fix_prompt("the target", "p.C.putValue", None, "SPECS", [],
                    "p.C.getValue", attempt=2)
    assert "did NOT go green" in f2 and "degraded" in f2
    c = cache_fix_prompt("the target", _GRAPH, [])
    assert "previous successful" in c
    assert "JSON" in GAMMA_FORMAT_REMINDER
