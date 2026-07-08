# tests/test_rcc_subgraph.py
import json

from abench.rcc_subgraph import RccSubgraph, build_subgraph, find_target_fqn


def _write_impact(tmp_path, coverage, methods=None):
    d = tmp_path / ".impact"
    d.mkdir()
    (d / "coverage.json").write_text(json.dumps(coverage))
    (d / "methods.json").write_text(json.dumps(methods or {}))
    return d


_COV = {
    "p.C.putValue": ["p.T1.a", "p.T1.b", "p.T2.c"],
    "p.C.getValue": ["p.T1.a", "p.T2.c"],          # overlap 2
    "p.C.parse":    ["p.T1.a"],                     # overlap 1
    "p.C.far":      ["p.T3.z"],                     # overlap 0 -> excluded
}


def test_find_target_matches_method_name_like_blast_radius():
    assert find_target_fqn(_COV, ["putValue"]) == "p.C.putValue"
    assert find_target_fqn(_COV, ["nosuch"]) is None
    assert find_target_fqn({}, ["putValue"]) is None


def test_build_subgraph_ranks_by_test_overlap_and_excludes_zero(tmp_path):
    impact = _write_impact(tmp_path, _COV)
    sub = build_subgraph(impact, tmp_path, ["putValue"])
    assert sub.target_fqn == "p.C.putValue"
    assert sub.methods == ["p.C.putValue", "p.C.getValue", "p.C.parse"]
    assert sub.test_fqns == ["p.T1.a", "p.T1.b", "p.T2.c"]
    assert sub.test_classes == ["p.T1", "p.T2"]


def test_build_subgraph_k_caps_neighbors(tmp_path):
    impact = _write_impact(tmp_path, _COV)
    sub = build_subgraph(impact, tmp_path, ["putValue"], k=1)
    assert sub.methods == ["p.C.putValue", "p.C.getValue"]


def test_build_subgraph_none_when_no_coverage_or_no_target(tmp_path):
    assert build_subgraph(tmp_path / "missing", tmp_path, ["putValue"]) is None
    impact = _write_impact(tmp_path, _COV)
    assert build_subgraph(impact, tmp_path, ["nosuch"]) is None


def test_build_subgraph_computes_pairwise_shared_test_edges(tmp_path):
    impact = _write_impact(tmp_path, _COV)
    sub = build_subgraph(impact, tmp_path, ["putValue"])
    # putValue={a,b,c}, getValue={a,c}, parse={a} -> pairwise intersections:
    # putValue&getValue=2, getValue&parse=1, putValue&parse=1 (tie broken by 'a')
    assert sub.shared_test_edges == [
        ("p.C.putValue", "p.C.getValue", 2),
        ("p.C.getValue", "p.C.parse", 1),
        ("p.C.putValue", "p.C.parse", 1),
    ]


def test_shared_test_edges_empty_for_single_method_subgraph(tmp_path):
    impact = _write_impact(tmp_path, {"p.C.putValue": ["p.T1.a"]})
    sub = build_subgraph(impact, tmp_path, ["putValue"])
    assert sub.shared_test_edges == []


def test_sources_read_span_with_margin_and_cap(tmp_path):
    src = tmp_path / "src" / "C.java"
    src.parent.mkdir(parents=True)
    src.write_text("\n".join(f"line{i}" for i in range(1, 101)))
    methods = {"p.C.putValue": {"file": "src/C.java", "start": 50, "end": 52}}
    impact = _write_impact(tmp_path, {"p.C.putValue": ["p.T1.a"]}, methods)
    sub = build_subgraph(impact, tmp_path, ["putValue"], margin=2, cap=10_000)
    text = sub.sources["p.C.putValue"]
    assert text.splitlines()[0] == "line48"          # start-1-margin (0-based 47)
    assert text.splitlines()[-1] == "line54"         # end+margin
    # missing file -> empty snippet, never a crash
    methods_bad = {"p.C.putValue": {"file": "nope.java", "start": 1, "end": 2}}
    impact2 = tmp_path / "i2"; impact2.mkdir()
    (impact2 / "coverage.json").write_text(json.dumps({"p.C.putValue": ["p.T1.a"]}))
    (impact2 / "methods.json").write_text(json.dumps(methods_bad))
    sub2 = build_subgraph(impact2, tmp_path, ["putValue"])
    assert sub2.sources["p.C.putValue"] == ""
