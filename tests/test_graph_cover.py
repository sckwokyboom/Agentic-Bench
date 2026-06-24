import json

from abench.graph_cover import blast_radius_keys, make_blast_radius_predicate
from abench.failure_report import TestFailure


def _f(cls, name):
    return TestFailure(classname=cls, name=name, kind="failure")


def test_blast_radius_keys_only_target_method_coverers():
    coverage = {
        "picocli.CommandLine$Help$TextTable.putValue": [
            "picocli.HelpTest.testWrap", "picocli.TextTableTest.testSpan"],
        "picocli.Other.unrelated": ["picocli.OtherTest.testX"],   # not a target → excluded
    }
    assert blast_radius_keys(coverage, ["putValue"]) == {
        "helptest.testwrap", "texttabletest.testspan"}


def test_predicate_matches_coverers(tmp_path):
    d = tmp_path / ".impact"; d.mkdir()
    (d / "coverage.json").write_text(json.dumps({
        "picocli.CommandLine$Help$TextTable.putValue": ["picocli.HelpTest.testWrap"]}))
    pred = make_blast_radius_predicate(d, ["putValue"])
    assert pred is not None
    assert pred(_f("picocli.HelpTest", "testWrap")) is True       # FQN form matches
    assert pred(_f("HelpTest", "testWrap")) is True               # bare Class.method too
    assert pred(_f("picocli.OtherTest", "testY")) is False


def test_predicate_none_without_data_or_match(tmp_path):
    assert make_blast_radius_predicate(tmp_path / "nope", ["putValue"]) is None
    d = tmp_path / "x"; d.mkdir()
    (d / "coverage.json").write_text('{"a.b": ["X.y"]}')   # no target method → None
    assert make_blast_radius_predicate(d, ["putValue"]) is None
