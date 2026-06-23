# Phased Orchestration — Plan 1: Foundation Utilities

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic, independently-testable leaf modules the phased orchestrator will compose — with no change to how runs execute yet.

**Architecture:** Pure/leaf Python modules under `abench/`, each one responsibility, each unit-tested in isolation (no LLM, no live gradle). A later plan (Orchestrator core) wires them behind a controller; another (Runner integration) exposes the `orchestration` condition. This plan is safe to merge on its own: it only adds modules + additive trace fields.

**Tech Stack:** Python 3 (stdlib only: `xml.etree.ElementTree`, `subprocess`, `re`, `dataclasses`), pytest. Follows existing abench patterns (`verify_parsers.py`, `trace_model.py`).

Spec: `docs/superpowers/specs/2026-06-23-phased-orchestration-design.md`.

---

## File structure (locked here)

- Create `abench/failure_report.py` — JUnit XML → `TestFailure[]` → prioritized `Cluster[]` (shared later with the `impact failures` CLI).
- Create `abench/git_snapshot.py` — full-worktree snapshot/restore + edit-allowlist check.
- Create `abench/regression_gate.py` — `SuiteResult` + multi-factor accept/revert decision.
- Create `abench/trace_stitch.py` — merge per-phase `Trace`s + controller steps → one `Trace`.
- Modify `abench/trace_model.py` — additive fields: `Step.phase`, `StepKind.CONTROLLER`, `Trace.orchestration_outcome` + controller-overhead counters.
- Tests: `tests/test_failure_report.py`, `tests/test_git_snapshot.py`, `tests/test_regression_gate.py`, `tests/test_trace_stitch.py`; extend `tests/test_trace_model.py`.

---

## Task 1: Additive trace-model fields

**Files:**
- Modify: `abench/trace_model.py`
- Test: `tests/test_trace_model.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_trace_model.py`)

```python
def test_orchestration_fields_roundtrip():
    from abench.trace_model import Step, StepKind, Trace, trace_from_dict
    trace = Trace(
        finished=True,
        orchestration_outcome="green",
        controller_test_runs=3,
        controller_test_time_s=12.5,
        accepted_rounds=2,
        reverted_rounds=1,
        steps=[Step(kind=StepKind.CONTROLLER, ts=1.0, turn=0,
                    text="ran suite -> 4 failures in 2 clusters", phase="diagnose")],
    )
    restored = trace_from_dict(json.loads(json.dumps(trace.to_dict())))
    assert restored == trace
    assert restored.steps[0].kind == StepKind.CONTROLLER
    assert restored.steps[0].phase == "diagnose"
    assert restored.orchestration_outcome == "green"
    assert restored.controller_test_runs == 3 and restored.reverted_rounds == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_trace_model.py::test_orchestration_fields_roundtrip -q`
Expected: FAIL — `AttributeError`/`TypeError` (no `CONTROLLER`, `phase`, or new Trace fields).

- [ ] **Step 3: Add the fields** (`abench/trace_model.py`)

Add to `StepKind`:
```python
    CONTROLLER = "controller"
```
Add to `Step` (after `patch`):
```python
    # Orchestration: the phase this step belongs to (None for the autonomous
    # baseline loop). CONTROLLER steps are deterministic controller actions.
    phase: str | None = None
```
Add to `Trace` (near `target_similarity`):
```python
    # Phased-orchestration outcome + controller overhead (None/0 for baseline).
    orchestration_outcome: str | None = None   # green|budget|stuck|compile-fail
    controller_test_runs: int = 0
    controller_test_time_s: float | None = None
    accepted_rounds: int = 0
    reverted_rounds: int = 0
```
(`to_dict`/`trace_from_dict` need no change — `asdict` + `**remaining` already round-trip new fields, and `Step(kind=...)` reconstruction is unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_trace_model.py -q`
Expected: PASS (all trace-model tests, old + new).

- [ ] **Step 5: Commit**

```bash
git add abench/trace_model.py tests/test_trace_model.py
git commit -m "feat(trace): additive orchestration fields (phase, CONTROLLER kind, outcome, overhead)"
```

---

## Task 2: `failure_report` — parse JUnit XML into structured failures

**Files:**
- Create: `abench/failure_report.py`
- Create fixture + test: `tests/test_failure_report.py`

- [ ] **Step 1: Write the failing test** (`tests/test_failure_report.py`)

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_failure_report.py -q`
Expected: FAIL — `ModuleNotFoundError: abench.failure_report`.

- [ ] **Step 3: Implement the parser** (`abench/failure_report.py`)

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_failure_report.py -q`
Expected: PASS (both parse tests).

- [ ] **Step 5: Commit**

```bash
git add abench/failure_report.py tests/test_failure_report.py
git commit -m "feat(failure_report): parse JUnit XML into structured TestFailure"
```

---

## Task 3: `failure_report` — cluster + prioritize + select representatives

**Files:**
- Modify: `abench/failure_report.py`
- Modify: `tests/test_failure_report.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_failure_report.py`)

```python
from abench.failure_report import cluster_failures, select_clusters, Cluster


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_failure_report.py -q`
Expected: FAIL — `ImportError: cannot import name 'cluster_failures'`.

- [ ] **Step 3: Implement clustering** (append to `abench/failure_report.py`)

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_failure_report.py -q`
Expected: PASS (parse + clustering tests).

- [ ] **Step 5: Commit**

```bash
git add abench/failure_report.py tests/test_failure_report.py
git commit -m "feat(failure_report): cluster failures with prioritized selection"
```

---

## Task 4: `git_snapshot` — robust worktree snapshot/restore + edit allowlist

**Files:**
- Create: `abench/git_snapshot.py`
- Create: `tests/test_git_snapshot.py`

- [ ] **Step 1: Write the failing test** (`tests/test_git_snapshot.py`)

```python
import subprocess
from pathlib import Path
from abench.git_snapshot import snapshot, restore, forbidden_changes


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True,
                   capture_output=True, text=True)


def _repo(tmp_path) -> Path:
    r = tmp_path / "wd"; r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t"); _git(r, "config", "user.name", "t")
    (r / "src").mkdir()
    (r / "src" / "A.java").write_text("orig\n")
    (r / "src" / "D.java").write_text("dee\n")
    _git(r, "add", "-A"); _git(r, "commit", "-qm", "seed")
    return r


def test_restore_reverts_modify_create_and_delete(tmp_path):
    r = _repo(tmp_path)
    snap = snapshot(r)
    (r / "src" / "A.java").write_text("changed\n")          # modify tracked
    (r / "src" / "B.java").write_text("new\n")               # create untracked
    (r / "src" / "D.java").unlink()                          # delete tracked
    (r / "C.txt").write_text("c"); _git(r, "add", "C.txt")   # stage a new file
    restore(r, snap)
    assert (r / "src" / "A.java").read_text() == "orig\n"    # modify reverted
    assert (r / "src" / "D.java").read_text() == "dee\n"     # delete restored
    assert not (r / "src" / "B.java").exists()               # untracked removed
    assert not (r / "C.txt").exists()                        # staged-new removed


def test_forbidden_changes_flags_non_allowlisted_paths(tmp_path):
    r = _repo(tmp_path)
    (r / "src" / "A.java").write_text("edit\n")              # allowed
    (r / "src").mkdir(exist_ok=True)
    (r / "build.gradle").write_text("x")                     # forbidden
    (r / "t.txt").write_text("y")                            # forbidden
    bad = forbidden_changes(r, allowed_prefixes=["src/"])
    assert "build.gradle" in bad and "t.txt" in bad and "src/A.java" not in bad
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_git_snapshot.py -q`
Expected: FAIL — `ModuleNotFoundError: abench.git_snapshot`.

- [ ] **Step 3: Implement** (`abench/git_snapshot.py`)

```python
"""Robust full-worktree snapshot/restore + edit allowlist for the orchestrator.

snapshot() records a tree object (tracked + currently-untracked, honoring
.gitignore so build/ is excluded); restore() rewinds the worktree to it,
including reverting modifications, deletions, and removing files created since.
Uses plumbing that never moves HEAD or the branch ref.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout


def snapshot(repo: Path) -> str:
    """Stage everything (respecting .gitignore) and return a tree SHA capturing
    the current worktree. Does not commit or move any ref."""
    _git(repo, "add", "-A")
    return _git(repo, "write-tree").strip()


def restore(repo: Path, tree: str) -> None:
    """Rewind the worktree to the snapshot tree: load it into the index, write
    every entry out (overwriting/restoring), then drop non-ignored files that
    are not in the snapshot. build/ etc. (gitignored) are left untouched."""
    _git(repo, "read-tree", tree)
    _git(repo, "checkout-index", "-a", "-f")
    _git(repo, "clean", "-fd")


def forbidden_changes(repo: Path, allowed_prefixes: list[str]) -> list[str]:
    """Changed paths (tracked or untracked) that fall OUTSIDE the allowlist —
    e.g. edits to src/test, build.gradle, configs. The orchestrator reverts
    these. Rename lines ('R old -> new') are reported verbatim for inspection."""
    out = _git(repo, "status", "--porcelain")
    changed: list[str] = []
    for ln in out.splitlines():
        if not ln.strip():
            continue
        path = ln[3:].strip()
        if " -> " in path:                      # rename: check the destination
            path = path.split(" -> ", 1)[1]
        changed.append(path)
    return [p for p in changed if not any(p.startswith(a) for a in allowed_prefixes)]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_git_snapshot.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add abench/git_snapshot.py tests/test_git_snapshot.py
git commit -m "feat(git_snapshot): robust worktree snapshot/restore + edit allowlist"
```

---

## Task 5: `regression_gate` — multi-factor accept/revert decision

**Files:**
- Create: `abench/regression_gate.py`
- Create: `tests/test_regression_gate.py`

- [ ] **Step 1: Write the failing test** (`tests/test_regression_gate.py`)

```python
from abench.regression_gate import SuiteResult, decide


def _s(**kw):
    base = dict(compiled=True, ran=True, executed=100, passed=80, failed=20, errors=0, skipped=0)
    base.update(kw)
    return SuiteResult(**base)


def test_accept_when_more_pass():
    ok, _ = decide(_s(passed=80, failed=20), _s(passed=85, failed=15))
    assert ok


def test_reject_when_compile_broken():
    ok, why = decide(_s(), _s(compiled=False))
    assert not ok and "compile" in why.lower()


def test_reject_when_fewer_tests_executed_even_if_failed_drops():
    # failed dropped 20->5 only because 90 tests no longer ran
    ok, why = decide(_s(executed=100, passed=80, failed=20), _s(executed=10, passed=5, failed=5))
    assert not ok and "execut" in why.lower()


def test_reject_when_new_errors_despite_failed_drop():
    ok, _ = decide(_s(failed=20, errors=0), _s(failed=18, errors=3))
    assert not ok


def test_reject_when_no_improvement():
    ok, _ = decide(_s(passed=80, failed=20), _s(passed=80, failed=20))
    assert not ok
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_regression_gate.py -q`
Expected: FAIL — `ModuleNotFoundError: abench.regression_gate`.

- [ ] **Step 3: Implement** (`abench/regression_gate.py`)

```python
"""Multi-factor regression gate for the diagnose loop.

`failed_count` alone is unsafe: a drop can hide tests that stopped running or
got skipped, or a worse scenario breaking while a trivial one is fixed. Accept a
round only if it compiles, the suite actually ran, no fewer tests executed, and
it strictly improved (more passing, or fewer failures with no new errors/skips).
The orchestrator confirms a regression by re-running the newly-failing tests
before reverting (flaky-robustness lives in the caller; this decision is pure).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SuiteResult:
    compiled: bool
    ran: bool                 # the suite executed (vs a build/infra error)
    executed: int             # number of tests that actually ran
    passed: int
    failed: int
    errors: int = 0
    skipped: int = 0


def decide(before: SuiteResult, after: SuiteResult) -> tuple[bool, str]:
    """Return (accept, reason). Accept => keep the edit as the new best."""
    if not after.compiled:
        return False, "does not compile"
    if not after.ran:
        return False, "test suite did not run (infra error)"
    if after.executed < before.executed:
        return False, (f"fewer tests executed ({after.executed} < {before.executed}) "
                       "— a failure-count drop here is not real progress")
    if after.errors > before.errors:
        return False, f"new errors ({before.errors} -> {after.errors})"
    if after.skipped > before.skipped:
        return False, f"more skipped ({before.skipped} -> {after.skipped})"
    if after.passed > before.passed:
        return True, f"more passing ({before.passed} -> {after.passed})"
    if after.failed < before.failed:
        return True, f"fewer failures ({before.failed} -> {after.failed})"
    return False, "no improvement"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_regression_gate.py -q`
Expected: PASS (all five cases).

- [ ] **Step 5: Commit**

```bash
git add abench/regression_gate.py tests/test_regression_gate.py
git commit -m "feat(regression_gate): multi-factor accept/revert decision"
```

---

## Task 6: `trace_stitch` — merge per-phase Traces + controller steps

**Files:**
- Create: `abench/trace_stitch.py`
- Create: `tests/test_trace_stitch.py`

- [ ] **Step 1: Write the failing test** (`tests/test_trace_stitch.py`)

```python
import json
from abench.trace_model import Step, StepKind, Trace, TurnInfo, trace_from_dict
from abench.trace_stitch import stitch


def _phase_trace(text, ts, tin, tout):
    return Trace(
        started_at=ts, ended_at=ts + 1,
        tokens_in=tin, tokens_out=tout,
        turns=[TurnInfo(message_id="m", reason="stop", tokens_in=tin, tokens_out=tout)],
        steps=[Step(kind=StepKind.ASSISTANT_TEXT, ts=ts, turn=0, text=text)],
    )


def test_stitch_concatenates_tags_and_sums():
    phases = [("understand", _phase_trace("read", 100.0, 10, 1)),
              ("implement", _phase_trace("edit", 200.0, 20, 2))]
    controller = [Step(kind=StepKind.CONTROLLER, ts=150.0, turn=0,
                       text="ran suite -> 4 failures", phase="implement")]
    t = stitch(phases, controller, outcome="green",
               controller_test_runs=1, controller_test_time_s=3.0,
               accepted_rounds=1, reverted_rounds=0)
    # round-trips
    t = trace_from_dict(json.loads(json.dumps(t.to_dict())))
    # steps ordered by ts, phase-tagged, controller step interleaved
    kinds = [(s.kind, s.phase) for s in t.steps]
    assert kinds == [(StepKind.ASSISTANT_TEXT, "understand"),
                     (StepKind.CONTROLLER, "implement"),
                     (StepKind.ASSISTANT_TEXT, "implement")]
    assert t.tokens_in == 30 and t.tokens_out == 3
    assert t.started_at == 100.0 and t.ended_at == 201.0
    assert t.orchestration_outcome == "green"
    assert t.controller_test_runs == 1 and t.accepted_rounds == 1
    assert len(t.turns) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_trace_stitch.py -q`
Expected: FAIL — `ModuleNotFoundError: abench.trace_stitch`.

- [ ] **Step 3: Implement** (`abench/trace_stitch.py`)

```python
"""Merge per-phase opencode Traces + controller steps into one stitched Trace,
so a phased run produces the same schema/metrics as the baseline (single-run)
trace. Token/cost are summed across phases (LLM-only). Steps are phase-tagged
and ordered by timestamp; controller steps interleave by their own ts.
"""
from __future__ import annotations

from .trace_model import Step, Trace, TurnInfo


def _sum(values: list[int | float | None]) -> int | float | None:
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def stitch(
    phases: list[tuple[str, Trace]],
    controller_steps: list[Step],
    *,
    outcome: str | None = None,
    controller_test_runs: int = 0,
    controller_test_time_s: float | None = None,
    accepted_rounds: int = 0,
    reverted_rounds: int = 0,
) -> Trace:
    steps: list[Step] = []
    turns: list[TurnInfo] = []
    for label, tr in phases:
        for s in tr.steps:
            s.phase = label                 # tag with the phase it came from
            steps.append(s)
        turns.extend(tr.turns)
    steps.extend(controller_steps)
    steps.sort(key=lambda s: (s.ts if s.ts is not None else 0.0))

    starts = [tr.started_at for _, tr in phases if tr.started_at is not None]
    ends = [tr.ended_at for _, tr in phases if tr.ended_at is not None]
    return Trace(
        steps=steps,
        turns=turns,
        started_at=min(starts) if starts else None,
        ended_at=max(ends) if ends else None,
        tokens_in=_sum([tr.tokens_in for _, tr in phases]),
        tokens_out=_sum([tr.tokens_out for _, tr in phases]),
        cost=_sum([tr.cost for _, tr in phases]),
        tokens_reasoning=_sum([tr.tokens_reasoning for _, tr in phases]),
        orchestration_outcome=outcome,
        controller_test_runs=controller_test_runs,
        controller_test_time_s=controller_test_time_s,
        accepted_rounds=accepted_rounds,
        reverted_rounds=reverted_rounds,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_trace_stitch.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add abench/trace_stitch.py tests/test_trace_stitch.py
git commit -m "feat(trace_stitch): merge per-phase traces + controller steps"
```

---

## Final: run the full foundation suite

- [ ] **Step 1: Run all new + touched tests**

Run: `python3 -m pytest tests/test_trace_model.py tests/test_failure_report.py tests/test_git_snapshot.py tests/test_regression_gate.py tests/test_trace_stitch.py -q`
Expected: PASS (all).

- [ ] **Step 2: Confirm no regression in trace-adjacent suite**

Run: `python3 -m pytest tests/test_safe_export_*.py tests/test_recompute.py tests/test_trace_normalize.py -q` (skip any that need pandas/cachetools)
Expected: PASS.

---

## Notes for Plans 2 & 3 (not this plan)

- **Plan 2 (orchestrator core):** `abench/orchestrator.py` phase machine — UNDERSTAND→IMPLEMENT→DIAGNOSE — composing these utilities + a fake `run_task` for the integration test. Assembles `SuiteResult` from compile result + JUnit XML; runs the flaky re-confirm (re-run newly-failing tests) before `regression_gate.decide`; uses `git_snapshot` for best/revert; emits `CONTROLLER` steps; calls `trace_stitch.stitch`. PLAN phase is the toggle layered after the core works.
- **Plan 3 (runner/config integration):** add `orchestration: str|None` to `Condition` (config.py:23); branch `runner.py` to `orchestrator.run` when set; baseline path untouched. Then runnable as a UI condition (`impact-only` vs `phased`).
- **Open implementation questions** (from the spec) to resolve in Plan 2: `run_task` session-per-phase vs continued; container/daemon/cache determinism across the controller's repeated suite runs; N / temperature / "meaningful improvement" threshold for the eval protocol.
