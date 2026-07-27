import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from abench.verify import (
    VerifyResult, augment_for_authoritative_run, augment_for_full_run,
    detect_command, run_verify, undercount_override,
)
from abench.verify_parsers import (
    parse_gradle_output,
    parse_maven_surefire,
    parse_pytest_output,
)


def test_augment_appends_gradle_continue():
    assert augment_for_full_run("./gradlew test") == "./gradlew test --continue"
    assert augment_for_full_run("gradle :core:test") == "gradle :core:test --continue"


def test_augment_appends_maven_fail_at_end():
    assert augment_for_full_run("mvn test") == "mvn test --fail-at-end"
    assert augment_for_full_run("./mvnw verify") == "./mvnw verify --fail-at-end"


def test_augment_is_idempotent():
    assert augment_for_full_run("./gradlew test --continue") == "./gradlew test --continue"
    assert augment_for_full_run("mvn -fae test") == "mvn -fae test"
    assert augment_for_full_run("mvn --fail-at-end test") == "mvn --fail-at-end test"


def test_augment_recognises_wrapped_commands():
    assert (augment_for_full_run("cd repo && ./gradlew test")
            == "cd repo && ./gradlew test --continue")


def test_augment_leaves_pytest_and_none_untouched():
    assert augment_for_full_run("pytest -q") == "pytest -q"
    assert augment_for_full_run(None) is None
    assert augment_for_full_run("") == ""


MAVEN_OK = "Tests run: 142, Failures: 0, Errors: 0, Skipped: 0"
MAVEN_FAIL = """\
Tests run: 142, Failures: 3, Errors: 0, Skipped: 0
Failed tests:
  com.example.FooTest.testA
  com.example.FooTest.testB
  com.example.BarTest.testC
"""

GRADLE_OK = "142 tests completed, 0 failed"
GRADLE_FAIL = """\
142 tests completed, 3 failed
com.example.FooTest > testA FAILED
com.example.FooTest > testB FAILED
com.example.BarTest > testC FAILED
"""

PYTEST_OK = "================ 12 passed in 0.45s ================="
PYTEST_FAIL = """\
FAILED tests/test_one.py::test_alpha - AssertionError
FAILED tests/test_two.py::test_beta
================ 10 passed, 2 failed in 0.62s ================
"""


def test_parse_maven_surefire_ok():
    p, f, names = parse_maven_surefire(MAVEN_OK)
    assert (p, f, names) == (142, 0, [])


def test_parse_maven_surefire_fail():
    p, f, names = parse_maven_surefire(MAVEN_FAIL)
    assert p == 139
    assert f == 3
    assert names == [
        "com.example.FooTest.testA",
        "com.example.FooTest.testB",
        "com.example.BarTest.testC",
    ]


def test_parse_gradle_ok():
    assert parse_gradle_output(GRADLE_OK) == (142, 0, [])


def test_parse_gradle_multi_module_sums_all_tasks():
    """A multi-module build prints one summary line per test task — they must be
    summed (not just the first), or a multi-module suite is under-counted and a
    failure in a later module is missed."""
    multi = (
        "> Task :picocli-core:test\n"
        "263 tests completed, 0 failed\n"
        "> Task :picocli-codegen:test\n"
        "89 tests completed, 2 failed\n"
    )
    p, f, _ = parse_gradle_output(multi)
    assert (p, f) == (350, 2)  # (263+89) total − 2 failed = 350 passed, 2 failed


def test_parse_gradle_fail():
    p, f, names = parse_gradle_output(GRADLE_FAIL)
    assert (p, f) == (139, 3)
    assert "com.example.FooTest > testA" in names


def test_parse_pytest_ok():
    assert parse_pytest_output(PYTEST_OK) == (12, 0, [])


def test_parse_pytest_fail():
    p, f, names = parse_pytest_output(PYTEST_FAIL)
    assert (p, f) == (10, 2)
    assert "tests/test_one.py::test_alpha" in names


def test_detect_command_maven(tmp_path):
    (tmp_path / "pom.xml").write_text("<project/>")
    assert detect_command(tmp_path) == "mvn test"


def test_detect_command_gradle_with_wrapper(tmp_path):
    (tmp_path / "build.gradle").write_text("")
    (tmp_path / "gradlew").write_text("#!/bin/sh")
    (tmp_path / "gradlew").chmod(0o755)
    assert detect_command(tmp_path) == "./gradlew test"


def test_detect_command_pytest(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "tests").mkdir()
    assert detect_command(tmp_path) == "pytest"


def test_detect_command_unknown(tmp_path):
    assert detect_command(tmp_path) is None


def test_run_verify_passed(tmp_path):
    """When the subprocess exits 0 and parser sees passed counts → status=passed."""
    fake_completed = subprocess.CompletedProcess(
        args=["mvn", "test"], returncode=0,
        stdout=MAVEN_OK, stderr="",
    )
    with patch("abench.verify.subprocess.run", return_value=fake_completed):
        result = run_verify(tmp_path, "mvn test", timeout_s=10)
    assert isinstance(result, VerifyResult)
    assert result.status == "passed"
    assert result.passed_count == 142
    assert result.failed_count == 0
    assert result.command == "mvn test"


def test_run_verify_failed(tmp_path):
    fake = subprocess.CompletedProcess(
        args=["mvn", "test"], returncode=1,
        stdout=MAVEN_FAIL, stderr="",
    )
    with patch("abench.verify.subprocess.run", return_value=fake):
        result = run_verify(tmp_path, "mvn test", timeout_s=10)
    assert result.status == "failed"
    assert result.failed_count == 3
    assert len(result.failed_names) == 3


def test_run_verify_timeout(tmp_path):
    def boom(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="mvn test", timeout=5)
    with patch("abench.verify.subprocess.run", side_effect=boom):
        result = run_verify(tmp_path, "mvn test", timeout_s=5)
    assert result.status == "timeout"


def test_run_verify_parse_error(tmp_path):
    """Non-zero exit + unparseable output → status=error, raw_output captured."""
    fake = subprocess.CompletedProcess(
        args=["mvn", "test"], returncode=1,
        stdout="some compiler crash", stderr="",
    )
    with patch("abench.verify.subprocess.run", return_value=fake):
        result = run_verify(tmp_path, "mvn test", timeout_s=10)
    assert result.status == "error"
    assert "compiler crash" in result.raw_output


class _FakePopen:
    """Popen stand-in for the STREAMING path: yields `output` line-by-line,
    then exits `rc`. Used to test the on_line tail without a real subprocess."""
    def __init__(self, output: str, rc: int):
        self.stdout = iter(output.splitlines(keepends=True))
        self._rc = rc
        self.returncode = None

    def wait(self, timeout=None):
        self.returncode = self._rc
        return self._rc

    def kill(self):
        pass


def test_run_verify_streams_lines_to_on_line(tmp_path):
    """With on_line set, run_verify uses the streaming path and delivers each
    output line live (this is the baseline-verify tail)."""
    seen: list[str] = []
    with patch("abench.verify.subprocess.Popen", return_value=_FakePopen(MAVEN_OK, 0)):
        result = run_verify(tmp_path, "mvn test", timeout_s=10, on_line=seen.append)
    assert result.status == "passed"          # streaming output still parses
    assert seen                               # lines were delivered live
    assert any("Tests run" in line for line in seen)


MAVEN_MULTI_CLASS = """\
[INFO] -------------------------------------------------------
[INFO]  T E S T S
[INFO] -------------------------------------------------------
[INFO] Running com.example.FooTest
[INFO] Tests run: 10, Failures: 0, Errors: 0, Skipped: 0
[INFO] Running com.example.BarTest
[INFO] Tests run: 5, Failures: 0, Errors: 0, Skipped: 0
[INFO] Results:
[INFO]
[INFO] Tests run: 15, Failures: 0, Errors: 0, Skipped: 0
"""


def test_parse_maven_uses_aggregate_not_first_class():
    p, f, _ = parse_maven_surefire(MAVEN_MULTI_CLASS)
    assert (p, f) == (15, 0)


PYTEST_WITH_ERROR = """\
ERROR tests/test_one.py::test_alpha - ImportError
================ 8 passed, 1 error in 0.45s ================
"""


def test_parse_pytest_treats_errors_as_failures():
    p, f, names = parse_pytest_output(PYTEST_WITH_ERROR)
    assert (p, f) == (8, 1)
    assert "tests/test_one.py::test_alpha" in names


def test_run_verify_returncode_nonzero_with_zero_failed_is_error(tmp_path):
    """Compile failure: mvn exits 1 but `Tests run: 0, Failures: 0` is parseable.
    Must classify as 'error', NOT 'failed'."""
    fake = subprocess.CompletedProcess(
        args=["mvn", "test"], returncode=1,
        stdout="Tests run: 0, Failures: 0, Errors: 0, Skipped: 0", stderr="",
    )
    with patch("abench.verify.subprocess.run", return_value=fake):
        result = run_verify(tmp_path, "mvn test", timeout_s=10)
    assert result.status == "error"


def test_detect_command_mvnw(tmp_path):
    (tmp_path / "pom.xml").write_text("")
    (tmp_path / "mvnw").write_text("#!/bin/sh")
    assert detect_command(tmp_path) == "./mvnw test"


GRADLE_FAIL_WITH_TASK_NOISE = """\
> Task :compileJava
> Task :test FAILED

com.example.FooTest > testA FAILED
    java.lang.AssertionError at FooTest.java:12

3 tests completed, 1 failed
"""


def test_parse_gradle_skips_task_lines_in_failed_names():
    _, _, names = parse_gradle_output(GRADLE_FAIL_WITH_TASK_NOISE)
    assert "com.example.FooTest > testA" in names
    # task lines (no ' > ') must NOT appear in failed names
    assert all(" > " in n for n in names)


# ── Classifier (reason + message) ────────────────────────────────────────────

def _run_classify(stdout="", stderr="", returncode=0, command="mvn test", raises=None):
    from unittest import mock

    if raises is not None:
        with mock.patch("abench.verify.subprocess.run", side_effect=raises):
            return run_verify(".", command, timeout_s=60)
    completed = mock.Mock(stdout=stdout, stderr=stderr, returncode=returncode)
    with mock.patch("abench.verify.subprocess.run", return_value=completed):
        return run_verify(".", command, timeout_s=60)


def test_tests_failed_with_counts():
    out = "Tests run: 10, Failures: 2, Errors: 0\nFailed tests:\n  com.x.AT.tb\n  com.x.AT.tc\n"
    r = _run_classify(stdout=out, returncode=1, command="mvn test")
    assert r.status == "failed"
    assert r.reason == "tests_failed"
    assert r.passed_count == 8 and r.failed_count == 2
    assert "2 of 10" in r.message


def test_passed():
    r = _run_classify(stdout="Tests run: 5, Failures: 0, Errors: 0\n", returncode=0, command="mvn test")
    assert r.status == "passed"
    assert r.reason == "passed"
    assert r.passed_count == 5 and r.failed_count == 0


def test_build_failed_when_no_summary_and_nonzero_exit():
    out = "[INFO] ...\n[ERROR] COMPILATION ERROR :\n[ERROR] Score.java:[10,5] cannot find symbol\nBUILD FAILURE\n"
    r = _run_classify(stdout=out, returncode=1, command="mvn test")
    assert r.status == "error"
    assert r.reason == "build_failed"
    assert "COMPILATION ERROR" in r.message or "build failed" in r.message


def test_tool_not_found_via_exit_127():
    r = _run_classify(stderr="mvn: command not found", returncode=127, command="mvn test")
    assert r.status == "error"
    assert r.reason == "tool_not_found"
    assert "mvn" in r.message


def test_tool_not_found_via_explicit_marker_nonzero_exit():
    # The "<tool>: command not found" line with a non-127 exit still counts.
    r = _run_classify(stderr="pytest: command not found\n", returncode=1, command="pytest")
    assert r.status == "error"
    assert r.reason == "tool_not_found"


def test_real_test_failure_with_not_found_in_message_is_not_tool_missing():
    # Regression: a genuine test failure whose output merely mentions the tool and
    # "not found" (e.g. an assertion message) must classify as tests_failed with
    # counts — NOT tool_not_found (which would drop the counts and flip success).
    out = (
        "1 passed, 1 failed in 0.3s\n"
        "FAILED tests/test_x.py::test_cfg - AssertionError: pytest: config key not found\n"
    )
    r = _run_classify(stdout=out, returncode=1, command="pytest")
    assert r.status == "failed"
    assert r.reason == "tests_failed"
    assert r.passed_count == 1 and r.failed_count == 1


def test_no_tests_run():
    r = _run_classify(stdout="Tests run: 0, Failures: 0, Errors: 0\n", returncode=0, command="mvn test")
    assert r.status == "error"
    assert r.reason == "no_tests"


def test_unparseable_zero_exit():
    r = _run_classify(stdout="some custom output, no summary", returncode=0, command="bash run.sh")
    assert r.status == "error"
    assert r.reason == "unparseable"


def test_timeout():
    r = _run_classify(command="mvn test", raises=subprocess.TimeoutExpired(cmd="mvn test", timeout=60))
    assert r.status == "timeout"
    assert r.reason == "timeout"


def test_raw_output_is_full_not_truncated():
    big = "x" * 20000 + "\nTests run: 1, Failures: 0, Errors: 0\n"
    r = _run_classify(stdout=big, returncode=0, command="mvn test")
    assert len(r.raw_output) >= 20000


def test_detect_verify_gradle_only(tmp_path):
    from abench.verify import detect_verify
    (tmp_path / "build.gradle").write_text("")
    (tmp_path / "gradlew").write_text("")
    d = detect_verify(tmp_path)
    assert d.system == "gradle" and d.command == "./gradlew test" and d.ambiguous is False


def test_detect_verify_maven_only(tmp_path):
    from abench.verify import detect_verify
    (tmp_path / "pom.xml").write_text("<project/>")
    d = detect_verify(tmp_path)
    assert d.system == "maven" and d.command == "mvn test" and d.ambiguous is False


def test_detect_verify_picocli_like_prefers_gradle_and_flags_ambiguous(tmp_path):
    from abench.verify import detect_verify
    (tmp_path / "build.gradle").write_text("")
    (tmp_path / "settings.gradle").write_text("")
    (tmp_path / "gradlew").write_text("")
    (tmp_path / "pom.xml").write_text("<project/>")
    d = detect_verify(tmp_path)
    assert d.system == "gradle" and d.command == "./gradlew test"
    assert d.ambiguous is True and set(d.candidates) == {"gradle", "maven"}


def test_detect_command_shim(tmp_path):
    from abench.verify import detect_command
    (tmp_path / "pom.xml").write_text("<project/>")
    assert detect_command(tmp_path) == "mvn test"
    assert detect_command(tmp_path / "empty") is None


def _write_junit_xml(path, tests, failures, errors=0, skipped=0, failed_cases=()):
    cases = "".join(
        f'<testcase classname="{c[0]}" name="{c[1]}"><failure/></testcase>'
        for c in failed_cases)
    path.write_text(
        f'<testsuite tests="{tests}" failures="{failures}" errors="{errors}" '
        f'skipped="{skipped}">{cases}</testsuite>')


def test_parse_results_xml_gradle(tmp_path):
    from abench.verify import _parse_results_xml
    d = tmp_path / "build/test-results/test"; d.mkdir(parents=True)
    _write_junit_xml(d / "TEST-a.xml", tests=10, failures=0)
    _write_junit_xml(d / "TEST-b.xml", tests=5, failures=2,
                     failed_cases=[("demo.BarTest", "tb"), ("demo.BarTest", "tc")])
    res = _parse_results_xml(tmp_path, "gradle")
    assert res is not None
    passed, failed, names = res
    assert passed == 13 and failed == 2
    assert "demo.BarTest.tb" in names


def test_parse_results_xml_maven(tmp_path):
    from abench.verify import _parse_results_xml
    d = tmp_path / "target/surefire-reports"; d.mkdir(parents=True)
    _write_junit_xml(d / "TEST-x.xml", tests=7, failures=0)
    res = _parse_results_xml(tmp_path, "maven")
    assert res == (7, 0, [])


def test_parse_results_xml_testsuites_wrapper(tmp_path):
    """Some tools wrap the suites in a <testsuites> root element; the parser must
    sum each child suite rather than ignoring the file."""
    from abench.verify import _parse_results_xml
    d = tmp_path / "build/test-results/test"; d.mkdir(parents=True)
    (d / "TEST-wrap.xml").write_text(
        '<testsuites>'
        '<testsuite tests="4" failures="0" errors="0" skipped="0"></testsuite>'
        '<testsuite tests="2" failures="1" errors="0" skipped="0">'
        '<testcase classname="demo.WrapTest" name="tx"><failure/></testcase>'
        '</testsuite>'
        '</testsuites>')
    res = _parse_results_xml(tmp_path, "gradle")
    assert res is not None
    passed, failed, names = res
    assert passed == 5 and failed == 1
    assert "demo.WrapTest.tx" in names


def test_parse_results_xml_none_when_absent(tmp_path):
    from abench.verify import _parse_results_xml
    assert _parse_results_xml(tmp_path, "gradle") is None


def test_run_verify_gradle_falls_back_to_xml_on_unparseable_stdout(tmp_path):
    """Modern Gradle: BUILD SUCCESSFUL but no 'N tests completed' line → use XML.
    The report is written *during* the run (gradle's test task), AFTER run_verify
    has cleared any stale results — so the side_effect simulates that write."""
    from unittest import mock
    from abench.verify import run_verify
    d = tmp_path / "build/test-results/test"
    completed = mock.Mock(stdout="BUILD SUCCESSFUL in 2s\n", stderr="", returncode=0)

    def _run(*a, **k):
        d.mkdir(parents=True, exist_ok=True)
        _write_junit_xml(d / "TEST-a.xml", tests=3, failures=0)
        return completed

    with mock.patch("abench.verify.subprocess.run", side_effect=_run):
        v = run_verify(tmp_path, "gradle test", timeout_s=60)
    assert v.status == "passed" and v.passed_count == 3 and v.reason == "passed"


def test_run_verify_does_not_trust_stale_xml_on_build_failure(tmp_path):
    """A stale green report from the agent's mid-task `gradle test` must NOT be
    read as success when the final build fails to compile (and writes no fresh
    report). run_verify clears the results dir before invoking the build, so the
    leftover green XML is gone and the failure falls through to build_failed."""
    from unittest import mock
    from abench.verify import run_verify
    d = tmp_path / "build/test-results/test"; d.mkdir(parents=True)
    _write_junit_xml(d / "TEST-stale.xml", tests=9, failures=0)  # stale GREEN
    # Compile failure: non-zero exit, no parseable summary, writes NO new report.
    completed = mock.Mock(
        stdout="",
        stderr="FAILURE: Build failed with an exception.\nerror: cannot find symbol\n",
        returncode=1)
    with mock.patch("abench.verify.subprocess.run", return_value=completed):
        v = run_verify(tmp_path, "gradle test", timeout_s=60)
    assert v.status == "error" and v.reason == "build_failed"
    assert v.passed_count != 9  # the stale green count must never leak through


def test_parser_for_sees_build_tool_behind_prefixes():
    """_parser_for must find the build tool even when the command is prefixed
    (cd&&, env=, timeout, sudo, bash -c) or path-qualified — otherwise an agent's
    `cd repo && ./gradlew test` parses to 0 tests."""
    from abench.verify import _parser_for
    from abench.verify_parsers import (
        parse_gradle_output, parse_maven_surefire, parse_pytest_output,
    )
    assert _parser_for("./gradlew test") is parse_gradle_output
    assert _parser_for("cd /tmp/picocli && ./gradlew test") is parse_gradle_output
    assert _parser_for("JAVA_HOME=/x ./gradlew :core:test") is parse_gradle_output
    assert _parser_for("timeout 600 ./gradlew test") is parse_gradle_output
    assert _parser_for('bash -lc "./gradlew test"') is parse_gradle_output
    assert _parser_for("/opt/app/gradlew test") is parse_gradle_output
    assert _parser_for("cd x && mvn -q test") is parse_maven_surefire
    assert _parser_for("JAVA_HOME=/x mvn verify") is parse_maven_surefire
    assert _parser_for("pytest -q") is parse_pytest_output
    assert _parser_for("echo hello") is None


# ── undercount guard + authoritative grading run ──────────────────────────────

def test_undercount_override_flags_gross_under_execution():
    # the phased artifact: ran 68 of ~2437, compiled (status 'failed') → invalid
    ov = undercount_override("failed", 58, 10, 2437)
    assert ov is not None
    assert ov[0] == "invalid" and ov[1] == "under_executed"
    assert "68" in ov[2] and "2437" in ov[2]


def test_undercount_override_passes_a_full_run():
    # a genuine failure runs the WHOLE suite under --continue (executed ≈ expected)
    assert undercount_override("failed", 2435, 2, 2437) is None
    assert undercount_override("passed", 2437, 0, 2437) is None


def test_undercount_override_ignores_non_verdict_and_missing_expected():
    assert undercount_override("error", 0, 0, 2437) is None      # compile/build error stays
    assert undercount_override("failed", 58, 10, None) is None   # no reference → can't judge
    assert undercount_override("failed", 58, 10, 0) is None


def test_augment_for_authoritative_run_forces_full_gradle_rerun():
    cmd = augment_for_authoritative_run("./gradlew test")
    assert "--rerun-tasks" in cmd and "--continue" in cmd
    assert augment_for_authoritative_run(cmd) == cmd             # idempotent
    # maven doesn't cache test up-to-date like gradle → no --rerun-tasks
    assert "--rerun-tasks" not in (augment_for_authoritative_run("mvn test") or "")


# ── Defects4J verify support ─────────────────────────────────────────────────
from abench.verify import (  # noqa: E402
    _grade_defects4j, _parse_defects4j, _system_for_command, _system_of,
)

_FAILING = ("--- org.jfree.chart.axis.junit.LogAxisTests::testFoo\n"
            "junit.framework.AssertionFailedError: ...\n\tat ...\n"
            "--- org.jfree.chart.junit.AreaChartTests::testBar\n"
            "java.lang.NullPointerException\n\tat ...\n")
_ALL = "\n".join(f"org.jfree.chart.T{i}::t" for i in range(20)) + "\n"


def test_system_recognises_defects4j():
    assert _system_of("defects4j test") == "defects4j"
    assert _system_for_command("cd /w && defects4j test") == "defects4j"
    assert _system_of("mvn test") == "maven" and _system_of("./gradlew test") == "gradle"


def test_parse_defects4j_from_files():
    passed, failed, names = _parse_defects4j(_FAILING, _ALL, "")
    assert failed == 2
    assert names == ["org.jfree.chart.axis.junit.LogAxisTests::testFoo",
                     "org.jfree.chart.junit.AreaChartTests::testBar"]
    assert passed == 18                                    # 20 executed - 2 failing


def test_parse_defects4j_stdout_fallback_when_no_files():
    out = "Running ant ...\nFailing tests: 2\n  - p.ATest::x\n  - p.BTest::y\n"
    passed, failed, names = _parse_defects4j(None, None, out)
    assert failed == 2 and names == ["p.ATest::x", "p.BTest::y"]
    assert passed is None                                  # total unknown → trust exit code


def test_grade_defects4j_green(tmp_path):
    (tmp_path / "failing_tests").write_text("")            # no failures
    (tmp_path / "all_tests").write_text(_ALL)
    v = _grade_defects4j(tmp_path, "Failing tests: 0", 0, "defects4j test", 1.0)
    assert v.status == "passed" and v.failed_count == 0 and v.passed_count == 20


def test_grade_defects4j_failed(tmp_path):
    (tmp_path / "failing_tests").write_text(_FAILING)
    (tmp_path / "all_tests").write_text(_ALL)
    v = _grade_defects4j(tmp_path, "Failing tests: 2", 0, "defects4j test", 1.0)
    assert v.status == "failed" and v.failed_count == 2
    assert v.passed_count == 18 and len(v.failed_names) == 2


def test_grade_defects4j_no_tests_is_error(tmp_path):
    (tmp_path / "failing_tests").write_text("")
    (tmp_path / "all_tests").write_text("")                # nothing executed
    v = _grade_defects4j(tmp_path, "", 0, "defects4j test", 1.0)
    assert v.status == "error" and v.reason == "no_tests"


def test_run_verify_routes_to_defects4j(tmp_path, monkeypatch):
    # A fake `defects4j` on PATH that writes the artifacts a green run would.
    bindir = tmp_path / "bin"; bindir.mkdir()
    (bindir / "defects4j").write_text(
        "#!/bin/sh\n: > failing_tests\n"
        "printf 'p.FooTest::t1\\np.FooTest::t2\\n' > all_tests\n"
        "echo 'Failing tests: 0'\n")
    (bindir / "defects4j").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{__import__('os').environ['PATH']}")
    wd = tmp_path / "wd"; wd.mkdir()
    v = run_verify(wd, "defects4j test", 60)
    assert v.status == "passed" and v.passed_count == 2 and v.failed_count == 0
