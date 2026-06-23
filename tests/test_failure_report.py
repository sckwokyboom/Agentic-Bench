from pathlib import Path
from abench.failure_report import (
    parse_junit_dir, TestFailure, cluster_failures, select_clusters, Cluster,
)


def _write(dir: Path, name: str, body: str) -> None:
    (dir / name).write_text(body)


def test_parse_extracts_comparison_failure_expected_actual(tmp_path):
    _write(tmp_path, "TEST-picocli.HelpTest.xml", """<?xml version="1.0"?>
<testsuite name="picocli.HelpTest" tests="2" failures="1" errors="0">
  <testcase name="testOk" classname="picocli.HelpTest"/>
  <testcase name="testTextTable" classname="picocli.HelpTest">
    <failure type="org.junit.ComparisonFailure"
             message="expected:&lt;  -v, [--verbose]&gt; but was:&lt;  -v,[--verbose]&gt;">
      stacktrace here
    </failure>
  </testcase>
</testsuite>""")
    fails = parse_junit_dir(tmp_path)
    assert len(fails) == 1
    f = fails[0]
    assert f.classname == "picocli.HelpTest" and f.name == "testTextTable"
    assert f.kind == "failure"
    assert f.expected == "  -v, [--verbose]" and f.actual == "  -v,[--verbose]"


def test_parse_error_without_expected_actual(tmp_path):
    _write(tmp_path, "TEST-picocli.TextTableTest.xml", """<?xml version="1.0"?>
<testsuite name="picocli.TextTableTest" tests="1" failures="0" errors="1">
  <testcase name="addRowValues" classname="picocli.TextTableTest">
    <error type="java.lang.StringIndexOutOfBoundsException" message="index 5 out of bounds">
      at picocli.CommandLine...
    </error>
  </testcase>
</testsuite>""")
    fails = parse_junit_dir(tmp_path)
    assert len(fails) == 1 and fails[0].kind == "error"
    assert fails[0].type == "java.lang.StringIndexOutOfBoundsException"
    assert fails[0].expected is None and fails[0].actual is None


def _f(cls, name, kind, type_, exp=None, act=None, msg="m"):
    return TestFailure(cls, name, kind, type_, msg, exp, act)


def test_digit_varying_same_shape_clusters_diff_shape_splits():
    # tA/tB differ only in digits -> normalized fingerprint is identical -> one
    # cluster; tC has a structurally different diff -> separate cluster.
    fails = [
        _f("picocli.HelpTest", "tA", "failure", "org.junit.ComparisonFailure", "col 12 [x]", "col 12[x]"),
        _f("picocli.ArgGroupTest", "tB", "failure", "org.junit.ComparisonFailure", "col 7 [x]", "col 7[x]"),
        _f("picocli.HelpTest", "tC", "failure", "org.junit.ComparisonFailure", "row1\nrow2", "row1"),
    ]
    clusters = cluster_failures(fails)
    assert len(clusters) == 2
    assert max(clusters, key=lambda c: c.count).count == 2


def test_exceptions_outrank_assertions_and_rare_severe_is_surfaced():
    fails = (
        [_f(f"C{i}", "t", "failure", "org.junit.ComparisonFailure", "p [q]", "p[q]") for i in range(6)]
        + [_f("IdxTest", "boom", "error", "java.lang.IndexOutOfBoundsException")]
    )
    selected = select_clusters(cluster_failures(fails), cap=1)
    # cap=1, but the rare severe exception cluster must still be surfaced
    assert any(c.representative.kind == "error" for c in selected)


def test_select_caps_to_three_distinct_clusters():
    # 10 structurally-distinct assertion clusters (letter length varies, not
    # normalized away) -> capped to 3.
    fails = [_f(f"C{i}", "t", "failure", "org.junit.ComparisonFailure",
                "x" * (i + 1) + " [y]", "x" * (i + 1) + "[y]") for i in range(10)]
    selected = select_clusters(cluster_failures(fails), cap=3)
    assert len(selected) == 3
