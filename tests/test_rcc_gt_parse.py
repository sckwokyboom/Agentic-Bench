# tests/test_rcc_gt_parse.py
import json
from pathlib import Path

from abench.rcc_gt_parse import parse_gt_graph

_GT_SAMPLE = Path("experiments/picocli-putValue/gt-out/slice-work/"
                  "357b6bd1af378e00.graph.json")


def _mini():
    return {
        "target": {"fqn": "p.C.put", "signature": "Cell(int,int)",
                   "file": "C.java", "line_start": 10, "line_end": 20,
                   "current_body": "SECRET CORRECT IMPL"},
        "method_bodies": {
            "p.C.get": {"fqn": "p.C.get", "signature": "Object()",
                        "file": "C.java", "line_start": 30, "line_end": 33,
                        "sliced_body": "Object get(){...}"},
        },
        "chains": [
            {"id": "c0", "depth": 2, "test": {"fqn": "p.CT.t1", "file": "T.java",
                                              "line": 5, "sliced_body": "assertX()"},
             "steps": [
                 {"caller_ref": "test", "callee_ref": "p.C.get",
                  "call_site": {"file": "T.java", "line": 5, "code": "c.get()"},
                  "args": [], "virtual": False},
                 {"caller_ref": "p.C.get", "callee_ref": "target",
                  "call_site": {"file": "C.java", "line": 31, "code": "put(r,c,v)"},
                  "args": [{"index": 0, "origin": "param", "value": "r"}],
                  "virtual": False},
             ]},
        ],
    }


def test_parse_drops_target_correct_body():
    g = parse_gt_graph(_mini())
    tv = g.vertex(g.target_id)
    assert tv.fqn == "p.C.put" and tv.is_changed is True
    assert tv.source is None
    assert "SECRET" not in json.dumps([v.__dict__ for v in g.vertices])


def test_parse_builds_typed_vertices_and_edges():
    g = parse_gt_graph(_mini())
    assert g.target_fqn == "p.C.put"
    assert set(g.methods()) == {"p.C.put", "p.C.get"}
    assert g.test_fqns == ["p.CT.t1"]
    assert g.vertex("method:p.C.get").source == "Object get(){...}"
    calls = {(e.src, e.tgt) for e in g.edges if e.type == "CALLS"}
    assert ("test:p.CT.t1", "method:p.C.get") in calls
    assert ("method:p.C.get", "method:p.C.put") in calls
    assert any(e.type == "TEST_ASSERTS" and e.src == "test:p.CT.t1"
               and e.tgt == "method:p.C.put" for e in g.edges)


def test_target_source_override_is_used_when_given():
    g = parse_gt_graph(_mini(), target_source="AGENT ATTEMPT BODY")
    assert g.vertex(g.target_id).source == "AGENT ATTEMPT BODY"


def test_parses_the_real_committed_gt_sample():
    if not _GT_SAMPLE.is_file():
        import pytest
        pytest.skip("gt-out sample not present")
    g = parse_gt_graph(json.loads(_GT_SAMPLE.read_text()))
    assert "putValue" in g.target_fqn
    assert g.vertex(g.target_id).source is None
    assert len(g.methods()) > 3 and len(g.test_fqns) > 10
    assert any(e.type == "CALLS" for e in g.edges)


def test_parse_preserves_chains_stats_and_directions():
    g = parse_gt_graph(_mini())
    # one chain per GT chain, ordered test-first, with a path id
    assert len(g.chains) == 1
    ch = g.chains[0]
    assert ch.test_fqn == "p.CT.t1"
    assert ch.node_ids[0] == "test:p.CT.t1" and ch.node_ids[-1] == "method:p.C.put"
    # edges carry directions + the chain's path id
    calls = [e for e in g.edges if e.type == "CALLS"]
    assert all(e.structural_direction and e.influence_direction for e in calls)
    assert any("p.CT.t1" in (e.path_ids and e.path_ids[0] or "") or e.path_ids
               for e in calls)
    # a TEST_ASSERTS edge is test→method structurally but method→test in influence
    ta = next(e for e in g.edges if e.type == "TEST_ASSERTS")
    assert ta.structural_direction == "test_to_method"
    assert ta.influence_direction == "method_to_test"
    assert g.change_origin["kind"] == "method_level_only"


def test_parse_carries_gt_stats_on_real_sample():
    import json as _json
    from pathlib import Path
    p = Path("experiments/picocli-putValue/gt-out/slice-work/357b6bd1af378e00.graph.json")
    if not p.is_file():
        import pytest
        pytest.skip("gt-out sample not present")
    g = parse_gt_graph(_json.loads(p.read_text()))
    assert g.stats.get("chain_count", 0) > 1000
    assert len(g.chains) > 1000
    assert g.stats.get("distinct_tests", 0) > 1000
