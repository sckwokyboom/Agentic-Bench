from pathlib import Path
from abench.failure_report import parse_junit_dir, TestFailure


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
