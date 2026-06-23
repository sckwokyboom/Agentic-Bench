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


@dataclass
class Cluster:
    signature: str
    severity: int                 # 2 = non-assertion exception (often root), 1 = assertion
    representative: TestFailure
    count: int = 0
    members: list[str] = field(default_factory=list)   # "Class.method"


_WS = re.compile(r"\s+")
_DIGITS = re.compile(r"\d+")


def _fingerprint(f: TestFailure) -> str:
    """Normalized shape of the failure: collapse whitespace runs and digits so
    'wrong wrap position' / 'missing space' style diffs that differ only in the
    concrete text bucket together, while structurally different diffs split."""
    if f.expected is not None and f.actual is not None:
        basis = f"{f.expected}\x1f{f.actual}"
    else:
        basis = f.message or ""
    basis = _DIGITS.sub("#", _WS.sub(" ", basis)).strip()
    return f"{f.type or f.kind}:{basis}"


def _severity(f: TestFailure) -> int:
    # A non-assertion exception (IndexOOB, NPE, StringIndexOOB) usually points at
    # the root bug; surface it above assertion mismatches.
    if f.kind == "error":
        return 2
    if f.type and "ComparisonFailure" not in f.type and "AssertionError" not in f.type:
        return 2
    return 1


def cluster_failures(failures: list[TestFailure]) -> list[Cluster]:
    by_sig: dict[str, Cluster] = {}
    for f in failures:
        sig = _fingerprint(f)
        c = by_sig.get(sig)
        member = f"{f.classname.rsplit('.', 1)[-1]}.{f.name}"
        if c is None:
            by_sig[sig] = Cluster(signature=sig, severity=_severity(f),
                                  representative=f, count=1, members=[member])
        else:
            c.count += 1
            c.members.append(member)
            # keep the shortest message as the clearest representative
            if len((f.message or "")) < len((c.representative.message or "")):
                c.representative = f
    return list(by_sig.values())


def select_clusters(clusters: list[Cluster], cap: int = 5) -> list[Cluster]:
    """Prioritize: severity desc, then count desc — but always surface at least
    one cluster of the highest severity present, even under the cap."""
    ordered = sorted(clusters, key=lambda c: (-c.severity, -c.count))
    if not ordered:
        return []
    chosen = ordered[:cap]
    top_sev = ordered[0].severity
    if not any(c.severity == top_sev for c in chosen):     # cap hid the severe ones
        chosen = [next(c for c in ordered if c.severity == top_sev)] + chosen[: cap - 1]
    return chosen
