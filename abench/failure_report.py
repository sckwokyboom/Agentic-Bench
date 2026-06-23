"""JUnit XML -> structured test failures -> prioritized clusters.

Shared by the phased orchestrator and (later) the `impact failures` CLI. Stdlib
only. Complements verify_parsers.py: that parses the stdout VERDICT (counts);
this reads build/test-results/**/TEST-*.xml for per-test expected/actual.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

# JUnit ComparisonFailure / AssertionError message: "expected:<X> but was:<Y>".
_EXP_ACT = re.compile(r"expected:?\s*<(?P<exp>.*?)>\s*but was:?\s*<(?P<act>.*?)>", re.DOTALL)


@dataclass
class TestFailure:
    __test__ = False            # name starts with "Test"; not a pytest test class
    classname: str
    name: str
    kind: str            # "failure" (assertion) | "error" (exception/infra)
    type: str | None = None     # exception class, e.g. org.junit.ComparisonFailure
    message: str | None = None
    expected: str | None = None
    actual: str | None = None


def _expected_actual(message: str | None) -> tuple[str | None, str | None]:
    if not message:
        return None, None
    m = _EXP_ACT.search(message)
    return (m.group("exp"), m.group("act")) if m else (None, None)


def parse_junit_dir(results_dir: Path) -> list[TestFailure]:
    """Parse every TEST-*.xml under results_dir into TestFailure for each
    <testcase> carrying a <failure> or <error>. Malformed files are skipped."""
    out: list[TestFailure] = []
    for xml in sorted(Path(results_dir).rglob("TEST-*.xml")):
        try:
            root = ET.fromstring(xml.read_text())
        except (OSError, ET.ParseError):
            continue
        for case in root.iter("testcase"):
            node = case.find("failure")
            kind = "failure"
            if node is None:
                node = case.find("error")
                kind = "error"
            if node is None:
                continue
            message = node.get("message")
            exp, act = _expected_actual(message)
            out.append(TestFailure(
                classname=case.get("classname") or "",
                name=case.get("name") or "",
                kind=kind,
                type=node.get("type"),
                message=message,
                expected=exp,
                actual=act,
            ))
    return out
