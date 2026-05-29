import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from abench.verify import VerifyResult, detect_command, run_verify
from abench.verify_parsers import (
    parse_gradle_output,
    parse_maven_surefire,
    parse_pytest_output,
)


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
