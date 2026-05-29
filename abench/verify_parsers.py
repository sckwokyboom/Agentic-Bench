"""Parsers for build/test tool outputs. Each parser returns (passed, failed, failed_names)."""
from __future__ import annotations

import re

_MAVEN_LINE = re.compile(
    r"Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+)"
)
_MAVEN_FAILED_NAME = re.compile(r"^\s+([\w.$]+\.[\w$]+)\s*$", re.MULTILINE)


def parse_maven_surefire(output: str) -> tuple[int, int, list[str]]:
    """Maven Surefire: `Tests run: X, Failures: Y, Errors: Z`."""
    m = _MAVEN_LINE.search(output)
    if not m:
        raise ValueError("no Maven Surefire summary found")
    run, failures, errors = (int(x) for x in m.groups())
    failed = failures + errors
    names: list[str] = []
    if failed and "Failed tests:" in output:
        block = output.split("Failed tests:", 1)[1]
        names = _MAVEN_FAILED_NAME.findall(block)[:20]
    return run - failed, failed, names


_GRADLE_LINE = re.compile(r"(\d+)\s+tests?\s+completed,\s+(\d+)\s+failed")
_GRADLE_FAILED_NAME = re.compile(r"^(.+?)\s+FAILED\s*$", re.MULTILINE)


def parse_gradle_output(output: str) -> tuple[int, int, list[str]]:
    """Gradle: `N tests completed, M failed`."""
    m = _GRADLE_LINE.search(output)
    if not m:
        raise ValueError("no Gradle summary found")
    total, failed = int(m.group(1)), int(m.group(2))
    names = _GRADLE_FAILED_NAME.findall(output)[:20]
    return total - failed, failed, names


_PYTEST_SUMMARY = re.compile(
    r"(?:(\d+)\s+passed)?(?:,\s*(\d+)\s+failed)?",
)
_PYTEST_SUMMARY_FULL = re.compile(
    r"(?P<passed>\d+)\s+passed(?:,\s*(?P<failed>\d+)\s+failed)?",
)
_PYTEST_FAILED_LINE = re.compile(r"^FAILED\s+(\S+)", re.MULTILINE)


def parse_pytest_output(output: str) -> tuple[int, int, list[str]]:
    """pytest: summary line `N passed[, M failed] in Xs`."""
    m = _PYTEST_SUMMARY_FULL.search(output)
    if not m:
        # accept fallback "N passed in Xs" or pure "M failed in Xs"
        failed_only = re.search(r"(\d+)\s+failed", output)
        if failed_only:
            failed = int(failed_only.group(1))
            names = _PYTEST_FAILED_LINE.findall(output)[:20]
            return 0, failed, names
        raise ValueError("no pytest summary found")
    passed = int(m.group("passed"))
    failed = int(m.group("failed") or 0)
    names = _PYTEST_FAILED_LINE.findall(output)[:20]
    return passed, failed, names
