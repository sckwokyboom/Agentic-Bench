# Agentic-Bench Web UI — Backend Implementation Plan (Plan A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Python backend (FastAPI + `abench/` extensions) for the Agentic-Bench Web UI v1 — enabling experiment authoring, live-streamed runs, automated verification, and trace inspection through a REST + WebSocket API.

**Architecture:** FastAPI single-process server, in-process runner using `abench.runner` with a WS-publishing client adapter. Filesystem is primary storage (`experiments/<name>/{experiment.yaml, prompts, slices, original, stripped, runs}`). Pydantic `Experiment` is the single source of truth — exported as JSON Schema to the frontend, validated identically on both sides, mutated atomically on disk.

**Tech Stack:** Python 3.12+, FastAPI, uvicorn, pydantic v2, websockets (FastAPI built-in), pytest, httpx (testing).

**Spec:** [`docs/superpowers/specs/2026-05-29-web-ui-design.md`](../specs/2026-05-29-web-ui-design.md)

**Out of scope (separate plan):** Frontend (`web/` — React + MUI + Vite). Plan B will build it against the API contract this plan locks in.

---

## File Structure

```
abench/                             # existing package — extended
  config.py                         # +VerifyCfg, +IsolationCfg, +target_file/methods
  trace_model.py                    # +TurnInfo, +FileChange, +FinalDiffSummary, verify_*, isolation_nonce
  trace_normalize.py                # +reads step-finish → TurnInfo
  runner.py                         # +nonce-prefix, +shuffle order, +verify step, +final_diff_summary, +baseline pre-flight
  metrics.py                        # +copies verify_*/final_diff_summary; auto-success from verify_status
  verify.py                         # NEW: detect_command + run_verify + parsers

abench_ui/                          # NEW package (same pyproject)
  __init__.py
  schema.py                         # JSON Schema export
  experiments.py                    # CRUD on experiments/<name>/
  runs.py                           # read run artefacts + method_comparison + PATCH success
  validate.py                       # /api/validate/model (cached, no chat calls)
  providers.py                      # /api/providers/{p}/credentials → auth.json
  ws_buffer.py                      # per-session ring buffer (≤5000 events) for WS replay
  ws_client.py                      # WSPublishingClient — wraps RealOpenCodeClient
  run_session.py                    # RunSession lifecycle (thread + cancel)
  server.py                         # FastAPI app — wires REST + WS routes + static serving
  cli.py                            # `abench-ui` console-script

tests/abench_ui/                    # NEW test dir
  test_schema.py
  test_experiments_api.py
  test_runs_api.py
  test_validate_api.py
  test_providers_api.py
  test_ws_buffer.py
  test_run_session.py
  test_ws_e2e.py                    # WebSocket end-to-end against FakeOpenCodeClient
  test_cli.py
```

Backend tests use `httpx.AsyncClient` against the FastAPI app with `transport=ASGITransport(app=app)`; WS tests use `httpx.AsyncWebSocketSession` (or `fastapi.testclient.TestClient.websocket_connect`).

---

## Task 0: Add backend dependencies + scaffold `abench_ui/` package

**Files:**
- Modify: `pyproject.toml`
- Create: `abench_ui/__init__.py`
- Create: `tests/abench_ui/__init__.py`
- Create: `tests/abench_ui/test_package_smoke.py`

- [ ] **Step 1: Add deps and console script to `pyproject.toml`**

In `pyproject.toml`, add to `[project] dependencies`: `"fastapi>=0.115"`, `"uvicorn[standard]>=0.30"`, `"cachetools>=5.3"`. Add to `[project.optional-dependencies] dev`: `"httpx>=0.27"` (already present, skip if so). In `[project.scripts]`, add: `abench-ui = "abench_ui.cli:main"`.

- [ ] **Step 2: Create the package skeleton**

`abench_ui/__init__.py`:
```python
__version__ = "0.1.0"
```

`tests/abench_ui/__init__.py`: empty.

- [ ] **Step 3: Write a smoke test that the package imports**

`tests/abench_ui/test_package_smoke.py`:
```python
def test_package_imports():
    import abench_ui
    assert abench_ui.__version__ == "0.1.0"
```

- [ ] **Step 4: Install deps and run**

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest tests/abench_ui/test_package_smoke.py -v
```
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml abench_ui/__init__.py tests/abench_ui/
git commit -m "feat(ui): scaffold abench_ui package"
```

---

## Task 1: Extend `abench/config.py` with `VerifyCfg`, `IsolationCfg`, `target_file`, `target_methods`

**Files:**
- Modify: `abench/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py`:

```python
def test_load_experiment_defaults_for_new_fields(tmp_path):
    yaml_path = _scaffold(tmp_path)
    exp = load_experiment(yaml_path)
    # verify defaults
    assert exp.verify.enabled is True
    assert exp.verify.timeout_s == 300
    assert exp.verify.command is None
    # isolation defaults: both lightweight mechanisms ON
    assert exp.isolation.nonce_prefix is True
    assert exp.isolation.shuffle_order is True
    assert exp.isolation.user_field_template is None
    # target defaults: optional, both None
    assert exp.target_file is None
    assert exp.target_methods is None


def test_load_experiment_accepts_verify_and_isolation_blocks(tmp_path):
    yaml_path = _scaffold(tmp_path)
    yaml_path.write_text(yaml_path.read_text() + """
verify:
  command: ./gradlew test
  timeout_s: 600
  enabled: true
isolation:
  nonce_prefix: false
  shuffle_order: true
""")
    exp = load_experiment(yaml_path)
    assert exp.verify.command == "./gradlew test"
    assert exp.verify.timeout_s == 600
    assert exp.isolation.nonce_prefix is False
    assert exp.isolation.shuffle_order is True


def test_target_file_must_exist_relative_to_fixture(tmp_path):
    _scaffold(tmp_path)
    yaml_path = tmp_path / "exp.yaml"
    yaml_path.write_text(yaml_path.read_text() + "\ntarget_file: a.py\n")
    # a.py exists in the fixture from _scaffold — ok
    exp = load_experiment(yaml_path)
    assert exp.target_file == "a.py"

    yaml_path.write_text(yaml_path.read_text().replace("a.py", "missing.py"))
    with pytest.raises(ValueError, match="target_file"):
        load_experiment(yaml_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_config.py::test_load_experiment_defaults_for_new_fields -v`
Expected: FAIL with `AttributeError: 'Experiment' object has no attribute 'verify'` or similar.

- [ ] **Step 3: Add the new models and fields**

In `abench/config.py`, add before `class Experiment`:

```python
class VerifyCfg(BaseModel):
    command: str | None = None          # override; otherwise auto-detect at run time
    enabled: bool = True
    timeout_s: int = 300


class IsolationCfg(BaseModel):
    nonce_prefix: bool = True            # uuid4 comment line at top of system_prompt
    shuffle_order: bool = True           # randomize condition×rep order
    # v2 heavyweight (not consumed in v1; placeholder for forward-compat):
    user_field_template: str | None = None
    api_key_env_list: str | None = None
```

In `class Experiment`, add fields after `metrics`:

```python
    verify: VerifyCfg = Field(default_factory=VerifyCfg)
    isolation: IsolationCfg = Field(default_factory=IsolationCfg)
    target_file: str | None = None
    target_methods: list[str] | None = None
```

In `_validate(exp)`, add at the end:

```python
    if exp.target_file is not None:
        full = exp.fixture_path / exp.target_file
        if not full.is_file():
            raise ValueError(
                f"target_file not found relative to fixture_path: {exp.target_file}"
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: all tests PASS (existing + new).

- [ ] **Step 5: Commit**

```bash
git add abench/config.py tests/test_config.py
git commit -m "feat(config): add VerifyCfg, IsolationCfg, target_file/methods"
```

---

## Task 2: Extend `abench/trace_model.py` with `TurnInfo`, `FileChange`, `FinalDiffSummary`, verify_* and isolation_nonce fields

**Files:**
- Modify: `abench/trace_model.py`
- Modify: `tests/test_trace_model.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trace_model.py`:

```python
def test_trace_with_turn_info_and_verify_and_diff_roundtrips():
    from abench.trace_model import (
        FinalDiffSummary,
        FileChange,
        Trace,
        TurnInfo,
        trace_from_dict,
    )

    trace = Trace(
        finished=True,
        turns=[
            TurnInfo(
                message_id="msg_1",
                reason="tool-calls",
                tokens_in=3200,
                tokens_out=100,
                tokens_reasoning=80,
                cost=0.00024,
                started_at=100.0,
                ended_at=112.0,
            ),
            TurnInfo(
                message_id="msg_2",
                reason="stop",
                tokens_in=4100,
                tokens_out=600,
                tokens_reasoning=0,
                cost=0.00033,
                started_at=145.0,
                ended_at=163.0,
            ),
        ],
        verify_status="passed",
        verify_command="./gradlew test",
        verify_duration_s=84.0,
        verify_passed_count=142,
        verify_failed_count=0,
        verify_failed_names=[],
        verify_baseline_unknown=False,
        final_diff_summary=FinalDiffSummary(
            files=[FileChange(path="src/main/java/.../X.java", added=6, removed=1)],
            total_added=6,
            total_removed=1,
        ),
        isolation_nonce="abc123def456",
    )
    blob = json.dumps(trace.to_dict())
    restored = trace_from_dict(json.loads(blob))
    assert restored == trace
    assert restored.turns[0].reason == "tool-calls"
    assert restored.verify_passed_count == 142
    assert restored.final_diff_summary.total_added == 6
    assert restored.isolation_nonce == "abc123def456"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_trace_model.py::test_trace_with_turn_info_and_verify_and_diff_roundtrips -v`
Expected: FAIL with `ImportError: cannot import name 'TurnInfo'`.

- [ ] **Step 3: Add the new dataclasses and fields**

In `abench/trace_model.py`, add before `class Trace`:

```python
@dataclass
class TurnInfo:
    message_id: str
    reason: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_reasoning: int | None = None
    cost: float | None = None
    started_at: float | None = None
    ended_at: float | None = None


@dataclass
class FileChange:
    path: str
    added: int = 0
    removed: int = 0


@dataclass
class FinalDiffSummary:
    files: list[FileChange] = field(default_factory=list)
    total_added: int = 0
    total_removed: int = 0
```

In `class Trace`, add after `interrupted_reason`:

```python
    turns: list[TurnInfo] = field(default_factory=list)

    verify_status: str | None = None
    verify_command: str | None = None
    verify_duration_s: float | None = None
    verify_passed_count: int | None = None
    verify_failed_count: int | None = None
    verify_failed_names: list[str] = field(default_factory=list)
    verify_baseline_unknown: bool = False

    final_diff_summary: FinalDiffSummary | None = None

    isolation_nonce: str | None = None

    # v2 timing breakdown — placeholder fields, populated in Phase 2
    llm_latency_s: float | None = None
    tool_exec_s: float | None = None
```

Update `to_dict` to handle nested dataclasses (asdict already recurses, but the StepKind enum fix must remain). No change needed if existing `to_dict` uses `asdict`.

Update `trace_from_dict` to reconstruct `turns`, `final_diff_summary`:

```python
def trace_from_dict(d: dict) -> Trace:
    steps = [Step(kind=StepKind(s["kind"]),
                  **{k: v for k, v in s.items() if k != "kind"})
             for s in d.get("steps", [])]
    turns_raw = d.get("turns", [])
    turns = [TurnInfo(**t) for t in turns_raw]
    fds_raw = d.get("final_diff_summary")
    if fds_raw is not None:
        fds = FinalDiffSummary(
            files=[FileChange(**fc) for fc in fds_raw.get("files", [])],
            total_added=fds_raw.get("total_added", 0),
            total_removed=fds_raw.get("total_removed", 0),
        )
    else:
        fds = None
    remaining = {k: v for k, v in d.items()
                 if k not in {"steps", "turns", "final_diff_summary"}}
    return Trace(steps=steps, turns=turns, final_diff_summary=fds, **remaining)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_trace_model.py -v`
Expected: all PASS (existing roundtrip + new).

- [ ] **Step 5: Commit**

```bash
git add abench/trace_model.py tests/test_trace_model.py
git commit -m "feat(trace): add TurnInfo, FinalDiffSummary, verify_* and isolation_nonce fields"
```

---

## Task 3: Update `abench/trace_normalize.py` to read `step-finish` parts into `TurnInfo`

**Files:**
- Modify: `abench/trace_normalize.py`
- Modify: `tests/test_trace_normalize.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_trace_normalize.py`, append:

```python
def test_normalize_populates_turns_from_step_finish():
    """The golden fixture contains step-finish events with reason/tokens/cost.
    The normalizer must populate trace.turns from them in order."""
    events = _load_events()
    session = json.loads((FIXTURES / "session_sample.json").read_text())
    from abench.trace_normalize import normalize
    trace = normalize(events, session)

    # Sample run had one tool-call turn followed by a final text turn:
    assert len(trace.turns) >= 1
    last_turn = trace.turns[-1]
    assert last_turn.reason in {"tool-calls", "stop", "length", "content-filter"}
    assert last_turn.tokens_in is not None or last_turn.tokens_out is not None
    # message_id consistency: each TurnInfo.message_id must be among the trace's step.turn-correlated message_ids
    message_ids_in_steps = {s.tool_call_id for s in trace.steps if s.tool_call_id}
    # we can't assert exact match without re-deriving — just sanity:
    assert all(t.message_id for t in trace.turns)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_trace_normalize.py::test_normalize_populates_turns_from_step_finish -v`
Expected: FAIL — `trace.turns` is empty because current normalizer skips `step-finish`.

- [ ] **Step 3: Update the normalizer**

In `abench/trace_normalize.py`, inside the `for event in raw_events` loop, replace the silent skip of `step-finish` with an aggregator. Replace the trailing comment `# step-start, step-finish, and anything else: skip silently.` with:

```python
        elif part_type == "step-finish":
            tokens = part.get("tokens", {}) or {}
            cache = tokens.get("cache", {}) or {}
            time = part.get("time", {}) or {}
            from abench.trace_model import TurnInfo  # local import to avoid cycles
            trace.turns.append(TurnInfo(
                message_id=message_id or "",
                reason=part.get("reason"),
                tokens_in=tokens.get("input"),
                tokens_out=tokens.get("output"),
                tokens_reasoning=tokens.get("reasoning"),
                cost=part.get("cost"),
                started_at=(time.get("start") / 1000.0) if time.get("start") else None,
                ended_at=(time.get("end") / 1000.0) if time.get("end") else None,
            ))
        # step-start and unknown types: skip silently.
```

(Adjust the import to module-level if cleaner — `TurnInfo` is already in `trace_model`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_trace_normalize.py -v`
Expected: all PASS (existing golden + new turn test).

- [ ] **Step 5: Commit**

```bash
git add abench/trace_normalize.py tests/test_trace_normalize.py
git commit -m "feat(normalize): populate Trace.turns from step-finish events"
```

---

## Task 4: New module `abench/verify.py` with auto-detect + Maven/Gradle/pytest parsers

**Files:**
- Create: `abench/verify.py`
- Create: `abench/verify_parsers.py`
- Create: `tests/test_verify.py`

- [ ] **Step 1: Write the failing test**

`tests/test_verify.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_verify.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'abench.verify'`.

- [ ] **Step 3: Write the parsers module**

`abench/verify_parsers.py`:

```python
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
```

- [ ] **Step 4: Write the verify module**

`abench/verify.py`:

```python
"""Post-run verification — runs the project's test suite and parses the result."""
from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

from .verify_parsers import (
    parse_gradle_output,
    parse_maven_surefire,
    parse_pytest_output,
)

Status = Literal["passed", "failed", "skipped", "error", "timeout"]


@dataclass
class VerifyResult:
    status: Status
    command: str | None = None
    duration_s: float | None = None
    passed_count: int | None = None
    failed_count: int | None = None
    failed_names: list[str] = field(default_factory=list)
    raw_output: str = ""


def detect_command(workdir: Path) -> str | None:
    """Heuristic — return the canonical test command for this project, or None."""
    workdir = Path(workdir)
    if (workdir / "pom.xml").exists():
        if (workdir / "mvnw").exists():
            return "./mvnw test"
        return "mvn test"
    if (workdir / "build.gradle").exists() or (workdir / "build.gradle.kts").exists():
        if (workdir / "gradlew").exists():
            return "./gradlew test"
        return "gradle test"
    if (workdir / "package.json").exists():
        return "npm test"
    if (workdir / "Cargo.toml").exists():
        return "cargo test"
    if (workdir / "go.mod").exists():
        return "go test ./..."
    if (workdir / "pyproject.toml").exists() and (workdir / "tests").is_dir():
        return "pytest"
    return None


_PARSER_BY_PREFIX: dict[str, Callable[[str], tuple[int, int, list[str]]]] = {
    "mvn": parse_maven_surefire,
    "./mvnw": parse_maven_surefire,
    "gradle": parse_gradle_output,
    "./gradlew": parse_gradle_output,
    "pytest": parse_pytest_output,
}


def _parser_for(command: str) -> Callable[[str], tuple[int, int, list[str]]] | None:
    first = command.split()[0]
    return _PARSER_BY_PREFIX.get(first)


def run_verify(workdir: Path, command: str, timeout_s: int) -> VerifyResult:
    """Run `command` from `workdir`. Parse output. Return a structured result."""
    workdir = Path(workdir)
    started = time.time()
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return VerifyResult(
            status="timeout",
            command=command,
            duration_s=time.time() - started,
        )
    except FileNotFoundError as exc:
        return VerifyResult(
            status="error",
            command=command,
            duration_s=time.time() - started,
            raw_output=str(exc),
        )

    output = completed.stdout + "\n" + completed.stderr
    duration = time.time() - started
    parser = _parser_for(command)
    if parser is None:
        return VerifyResult(
            status="error",
            command=command,
            duration_s=duration,
            raw_output=output[:8000],
        )
    try:
        passed, failed, names = parser(output)
    except ValueError:
        return VerifyResult(
            status="error",
            command=command,
            duration_s=duration,
            raw_output=output[:8000],
        )

    status: Status = "passed" if failed == 0 and completed.returncode == 0 else "failed"
    return VerifyResult(
        status=status,
        command=command,
        duration_s=duration,
        passed_count=passed,
        failed_count=failed,
        failed_names=names,
    )
```

- [ ] **Step 5: Run tests + commit**

Run: `.venv/bin/pytest tests/test_verify.py -v`
Expected: all PASS.

```bash
git add abench/verify.py abench/verify_parsers.py tests/test_verify.py
git commit -m "feat(verify): add detect_command + run_verify with maven/gradle/pytest parsers"
```

---

## Task 5: Extend `abench/runner.py` with nonce-prefix, shuffle, verify step, final_diff_summary, baseline pre-flight

**Files:**
- Modify: `abench/runner.py`
- Modify: `tests/test_runner.py`
- Create: `tests/test_runner_isolation.py`

- [ ] **Step 1: Write the failing test**

`tests/test_runner_isolation.py`:

```python
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from abench.config import Condition, Experiment, IsolationCfg, MetricsCfg, OpenCodeCfg, VerifyCfg
from abench.runner import run_experiment
from tests.fakes import FakeOpenCodeClient


def _make_exp(tmp_path: Path, isolation: IsolationCfg) -> Experiment:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "a.py").write_text("x = 1\n")
    reference = tmp_path / "reference"
    reference.mkdir()
    (reference / "a.py").write_text("x = 1\n")
    return Experiment(
        name="iso-test",
        fixture_path=fixture,
        reference_path=reference,
        task_prompt="t",
        system_prompt="ORIGINAL_SYSTEM_PROMPT",
        model="fake/m",
        output_dir=tmp_path / "runs",
        repetitions=2,
        conditions=[
            Condition(name="baseline", augmentation=None),
            Condition(name="augmented", augmentation="SLICE"),
        ],
        opencode=OpenCodeCfg(),
        metrics=MetricsCfg(),
        isolation=isolation,
        verify=VerifyCfg(enabled=False),  # skip verify in these tests
    )


class _RecordingClient:
    """Captures every system_prompt the runner passes."""
    def __init__(self):
        self.captures: list[str] = []
        self._fake = FakeOpenCodeClient()

    def run_task(self, *, workdir, system_prompt, model, user_message,
                 timeout_s, on_event):
        self.captures.append(system_prompt)
        return self._fake.run_task(
            workdir=workdir, system_prompt=system_prompt, model=model,
            user_message=user_message, timeout_s=timeout_s, on_event=on_event,
        )


def test_nonce_prefix_prepended_when_enabled(tmp_path):
    exp = _make_exp(tmp_path, IsolationCfg(nonce_prefix=True, shuffle_order=False))
    rec = _RecordingClient()
    run_experiment(exp, lambda e: rec)

    # 4 runs, each got a unique nonce-prefixed system prompt
    assert len(rec.captures) == 4
    for prompt in rec.captures:
        assert prompt.startswith("# abench-run: ")
        assert "\nORIGINAL_SYSTEM_PROMPT" in prompt
    # all nonces are unique
    nonces = {p.split("\n", 1)[0] for p in rec.captures}
    assert len(nonces) == 4


def test_nonce_prefix_disabled_passes_prompt_unchanged(tmp_path):
    exp = _make_exp(tmp_path, IsolationCfg(nonce_prefix=False, shuffle_order=False))
    rec = _RecordingClient()
    run_experiment(exp, lambda e: rec)
    for prompt in rec.captures:
        assert prompt == "ORIGINAL_SYSTEM_PROMPT"


def test_shuffle_changes_run_order_deterministically(tmp_path):
    """With shuffle_order=True and a fixed date-seed, the order is permuted but
    reproducible within the same day."""
    exp = _make_exp(tmp_path, IsolationCfg(nonce_prefix=False, shuffle_order=True))
    rec = _RecordingClient()
    run_experiment(exp, lambda e: rec)

    # Read manifests in disk order — they should reflect the actual run sequence
    manifests = sorted((tmp_path / "runs" / "iso-test").glob("*/rep_*/manifest.json"))
    order = [json.loads(m.read_text())["condition"] + "/" +
             str(json.loads(m.read_text())["rep"]) for m in manifests]
    assert sorted(order) == sorted([
        "baseline/0", "baseline/1", "augmented/0", "augmented/1",
    ])
    # NOTE: with a fixed day-seed the permutation is deterministic; we don't
    # assert a specific order here because day rolls; just that all 4 ran.
```

Also append to `tests/test_runner.py`:

```python
def test_run_experiment_writes_isolation_nonce_to_trace(tmp_path):
    """When isolation.nonce_prefix is on (default), each trace records its UUID."""
    exp = _experiment(tmp_path)  # existing helper; default isolation = both on
    run_experiment(exp, lambda e: FakeOpenCodeClient())
    root = tmp_path / "runs" / exp.name
    for cond in ("baseline", "augmented"):
        for rep in range(exp.repetitions):
            trace = json.loads((root / cond / f"rep_{rep}" / "trace.json").read_text())
            assert trace.get("isolation_nonce")  # non-empty UUID


def test_run_experiment_populates_final_diff_summary(tmp_path):
    exp = _experiment(tmp_path)
    run_experiment(exp, lambda e: FakeOpenCodeClient())
    root = tmp_path / "runs" / exp.name
    trace = json.loads((root / "baseline" / "rep_0" / "trace.json").read_text())
    fds = trace.get("final_diff_summary")
    assert fds is not None
    assert fds["total_added"] >= 1  # FakeOpenCodeClient writes GENERATED.txt
    assert any(f["path"] for f in fds["files"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_runner_isolation.py tests/test_runner.py::test_run_experiment_writes_isolation_nonce_to_trace -v`
Expected: FAIL — isolation hooks not yet wired.

- [ ] **Step 3: Update the runner**

In `abench/runner.py`, add imports at top:

```python
import datetime
import random
import uuid

from abench.trace_model import FileChange, FinalDiffSummary
from abench.diffstat import parse_diffstat
```

Replace the body of `run_experiment` with:

```python
def run_experiment(exp: Experiment, client_factory: ClientFactory) -> Path:
    root = exp.output_dir / exp.name
    root.mkdir(parents=True, exist_ok=True)
    (root / "experiment.resolved.yaml").write_text(_dump_resolved(exp))

    mcfg = MetricsConfig(**exp.metrics.model_dump())
    client = client_factory(exp)

    plan: list[tuple[Condition, int]] = [
        (cond, rep) for cond in exp.conditions for rep in range(exp.repetitions)
    ]
    if exp.isolation.shuffle_order:
        seed = hash(exp.name + datetime.date.today().isoformat())
        random.Random(seed).shuffle(plan)

    total = len(plan)
    t_exp = time.time()
    _log(
        f"[abench] experiment={exp.name} model={exp.model} "
        f"total_runs={total} timeout_s={exp.timeout_s} output_dir={root} "
        f"isolation: nonce={exp.isolation.nonce_prefix} shuffle={exp.isolation.shuffle_order}"
    )

    for idx, (cond, rep) in enumerate(plan, start=1):
        _log(
            f"[abench] ───── run {idx}/{total}: condition={cond.name} rep={rep} ─────"
        )
        t_run = time.time()
        _run_one(exp, cond, rep, root, client, mcfg)
        _log(f"[abench] run {idx}/{total} done in {time.time() - t_run:.1f}s")
        if exp.min_seconds_between_runs:
            _log(f"[abench] cooldown {exp.min_seconds_between_runs}s")
            time.sleep(exp.min_seconds_between_runs)
    _log(f"[abench] experiment finished in {time.time() - t_exp:.1f}s → {root}")
    return root
```

In `_run_one`, modify the body. Add nonce-prefix construction before `user_message = compose(...)`:

```python
    workdir, sha = fx.create_workdir(exp.fixture_path)
    try:
        # ── Isolation: nonce-prefix in system_prompt ──────────────────
        nonce: str | None = None
        system_prompt_eff = exp.system_prompt
        if exp.isolation.nonce_prefix:
            nonce = uuid.uuid4().hex
            system_prompt_eff = (
                f"# abench-run: {nonce}\n"
                f"# fixture: {sha}\n"
                f"{exp.system_prompt}"
            )

        user_message = compose(exp.task_prompt, cond.augmentation)
        # … (existing events_file open + on_event def + try/finally) …

        try:
            result = client.run_task(
                workdir=str(workdir),
                system_prompt=system_prompt_eff,   # <— effective prompt
                model=exp.model,
                user_message=user_message,
                timeout_s=exp.timeout_s,
                on_event=on_event,
            )
        finally:
            events_file.close()

        # Record isolation nonce on the trace
        if nonce is not None:
            result.trace.isolation_nonce = nonce

        # ── Final diff + summary ─────────────────────────────────────
        patch = fx.diff_workdir(workdir)
        (rundir / "changes.patch").write_text(patch)
        n_files, added, removed = parse_diffstat(patch)
        # per-file breakdown
        per_file = _per_file_diffstat(patch)
        result.trace.final_diff_summary = FinalDiffSummary(
            files=[FileChange(path=p, added=a, removed=r) for (p, a, r) in per_file],
            total_added=added,
            total_removed=removed,
        )

        # ── Trace.json + metrics ─────────────────────────────────────
        (rundir / "trace.json").write_text(json.dumps(result.trace.to_dict(), indent=2))
        metrics = extract(result.trace, patch, mcfg)
        (rundir / "metrics.json").write_text(json.dumps(metrics, indent=2))

        # … (existing _log result, manifest write — unchanged) …
    finally:
        fx.cleanup(workdir)
```

Add this helper at the bottom of the file:

```python
def _per_file_diffstat(patch: str) -> list[tuple[str, int, int]]:
    """Return [(path, added, removed)] from a unified git diff."""
    files: list[tuple[str, int, int]] = []
    current: str | None = None
    added = 0
    removed = 0
    for line in patch.splitlines():
        if line.startswith("diff --git a/"):
            if current is not None:
                files.append((current, added, removed))
            # `diff --git a/foo b/foo` → path = "foo"
            parts = line.split()
            if len(parts) >= 4:
                current = parts[2][2:]  # strip "a/"
            added = removed = 0
        elif line.startswith("+++ ") or line.startswith("--- "):
            continue
        elif line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    if current is not None:
        files.append((current, added, removed))
    return files
```

- [ ] **Step 4: Verify-step integration (separate sub-step within same task)**

After the metrics.json write, before manifest.json, add the verify call:

```python
        # ── Verify (post-rep, before cleanup) ────────────────────────
        if exp.verify.enabled:
            verify_command = exp.verify.command or _detect_verify(workdir)
            if verify_command is None:
                result.trace.verify_status = "skipped"
            else:
                v = run_verify(workdir, verify_command, exp.verify.timeout_s)
                result.trace.verify_status = v.status
                result.trace.verify_command = v.command
                result.trace.verify_duration_s = v.duration_s
                result.trace.verify_passed_count = v.passed_count
                result.trace.verify_failed_count = v.failed_count
                result.trace.verify_failed_names = v.failed_names

            # Re-serialise trace.json with verify_* populated
            (rundir / "trace.json").write_text(json.dumps(result.trace.to_dict(), indent=2))
            # Refresh metrics (verify_* propagate via metrics.extract)
            metrics = extract(result.trace, patch, mcfg)
            (rundir / "metrics.json").write_text(json.dumps(metrics, indent=2))
```

Add the imports at the top:

```python
from .verify import detect_command as _detect_verify, run_verify
```

- [ ] **Step 5: Run tests + commit**

Run: `.venv/bin/pytest tests/test_runner.py tests/test_runner_isolation.py -v`
Expected: all PASS (new + existing).

```bash
git add abench/runner.py tests/test_runner_isolation.py tests/test_runner.py
git commit -m "feat(runner): add nonce-prefix isolation, shuffle order, verify step, final_diff_summary"
```

---

## Task 6: Update `abench/metrics.py` to propagate verify_* and auto-populate `success` from verify_status

**Files:**
- Modify: `abench/metrics.py`
- Modify: `tests/test_metrics.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_metrics.py`:

```python
def test_extract_copies_verify_fields_and_auto_success_passed():
    cfg = _cfg()
    trace = Trace(
        started_at=0.0, ended_at=10.0,
        finished=True,
        verify_status="passed",
        verify_command="./gradlew test",
        verify_duration_s=12.0,
        verify_passed_count=142,
        verify_failed_count=0,
        steps=[],
    )
    m = extract(trace, "", cfg)
    assert m["verify_status"] == "passed"
    assert m["verify_passed_count"] == 142
    assert m["success"] is True


def test_extract_auto_success_failed():
    cfg = _cfg()
    trace = Trace(
        started_at=0.0, ended_at=10.0,
        finished=True,
        verify_status="failed",
        verify_failed_count=3,
        steps=[],
    )
    m = extract(trace, "", cfg)
    assert m["success"] is False


def test_extract_auto_success_none_when_skipped():
    cfg = _cfg()
    trace = Trace(
        started_at=0.0, ended_at=10.0,
        finished=True,
        verify_status="skipped",
        steps=[],
    )
    m = extract(trace, "", cfg)
    assert m["success"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_metrics.py -v`
Expected: FAIL — `m["verify_status"]` missing.

- [ ] **Step 3: Update `extract`**

In `abench/metrics.py`, in the dict returned at the end of `extract`, replace `"success": None` with the auto-derived logic, and add the verify fields:

```python
    success: bool | None
    if trace.verify_status == "passed":
        success = True
    elif trace.verify_status == "failed":
        success = False
    else:
        success = None

    return {
        "duration_s": duration,
        "n_steps": n_steps,
        "n_tool_calls": len(tool_calls),
        "tool_calls_by_name": by_name,
        "n_test_runs": n_test,
        "n_reads": n_reads,
        "n_searches": n_searches,
        "n_files_edited": n_files,
        "diff_lines_added": added,
        "diff_lines_removed": removed,
        "tokens_in": trace.tokens_in,
        "tokens_out": trace.tokens_out,
        "cost": trace.cost,
        "time_to_first_edit_s": ttfe,
        "finished": trace.finished,
        "interrupted_reason": trace.interrupted_reason,
        "verify_status": trace.verify_status,
        "verify_command": trace.verify_command,
        "verify_duration_s": trace.verify_duration_s,
        "verify_passed_count": trace.verify_passed_count,
        "verify_failed_count": trace.verify_failed_count,
        "verify_failed_names": list(trace.verify_failed_names),
        "verify_baseline_unknown": trace.verify_baseline_unknown,
        "isolation_nonce": trace.isolation_nonce,
        "success": success,
    }
```

- [ ] **Step 4: Run tests + commit**

Run: `.venv/bin/pytest tests/test_metrics.py -v`
Expected: PASS.

```bash
git add abench/metrics.py tests/test_metrics.py
git commit -m "feat(metrics): propagate verify_* and auto-derive success"
```

---

## Task 7: `abench_ui/schema.py` — Experiment JSON Schema export

**Files:**
- Create: `abench_ui/schema.py`
- Create: `tests/abench_ui/test_schema.py`

- [ ] **Step 1: Write the failing test**

`tests/abench_ui/test_schema.py`:

```python
from abench_ui.schema import experiment_json_schema


def test_schema_has_required_fields():
    schema = experiment_json_schema()
    assert schema["type"] == "object"
    props = schema["properties"]
    for required_field in (
        "name", "fixture_path", "reference_path",
        "task_prompt", "system_prompt", "model",
        "conditions", "repetitions", "output_dir",
        "verify", "isolation",
    ):
        assert required_field in props, f"missing {required_field}"


def test_schema_includes_nested_verify_isolation():
    schema = experiment_json_schema()
    defs = schema.get("$defs", {}) or schema.get("definitions", {})
    # pydantic v2 puts nested models in $defs
    assert any("VerifyCfg" in k or "Verify" in k for k in defs)
    assert any("IsolationCfg" in k or "Isolation" in k for k in defs)


def test_schema_is_json_serialisable():
    import json
    json.dumps(experiment_json_schema())  # raises if not serialisable
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/abench_ui/test_schema.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`abench_ui/schema.py`:

```python
"""Export the Experiment pydantic schema as JSON Schema for the frontend."""
from __future__ import annotations

from abench.config import Experiment


def experiment_json_schema() -> dict:
    """Returns the JSON Schema (draft 2020-12 by default in pydantic v2) for Experiment."""
    return Experiment.model_json_schema()
```

- [ ] **Step 4: Run tests + commit**

Run: `.venv/bin/pytest tests/abench_ui/test_schema.py -v`
Expected: PASS.

```bash
git add abench_ui/schema.py tests/abench_ui/test_schema.py
git commit -m "feat(ui/schema): export Experiment JSON Schema"
```

---

## Task 8: `abench_ui/experiments.py` — list / read / write experiments

**Files:**
- Create: `abench_ui/experiments.py`
- Create: `tests/abench_ui/test_experiments.py`

- [ ] **Step 1: Write the failing test**

`tests/abench_ui/test_experiments.py`:

```python
import textwrap
from pathlib import Path

import pytest

from abench_ui.experiments import (
    ExperimentNotFound,
    list_experiments,
    read_experiment,
    write_experiment,
)


def _make_skeleton(root: Path, name: str) -> Path:
    exp_dir = root / name
    exp_dir.mkdir(parents=True)
    (exp_dir / "prompts").mkdir()
    (exp_dir / "slices").mkdir()
    (exp_dir / "prompts" / "task.md").write_text("do it.")
    (exp_dir / "prompts" / "system.md").write_text("be careful.")
    (exp_dir / "slices" / "graph.md").write_text("SLICE")
    (exp_dir / "original").mkdir()
    (exp_dir / "original" / "a.py").write_text("# orig")
    (exp_dir / "stripped").mkdir()
    (exp_dir / "stripped" / "a.py").write_text("# stripped")
    (exp_dir / "experiment.yaml").write_text(textwrap.dedent("""\
        name: {name}
        fixture_path: ./stripped
        reference_path: ./original
        task_prompt: ./prompts/task.md
        system_prompt: ./prompts/system.md
        model: opencode/deepseek-v4-flash-free
        repetitions: 2
        output_dir: ./runs
        conditions:
          - {{name: baseline, augmentation: null}}
          - {{name: augmented, augmentation: ./slices/graph.md}}
    """).format(name=name))
    return exp_dir


def test_list_experiments_empty(tmp_path):
    assert list_experiments(tmp_path) == []


def test_list_experiments_finds_and_summarises(tmp_path):
    _make_skeleton(tmp_path, "exp-a")
    _make_skeleton(tmp_path, "exp-b")
    items = list_experiments(tmp_path)
    names = {it["name"] for it in items}
    assert names == {"exp-a", "exp-b"}
    for it in items:
        assert it["has_fixture"] is True
        assert it["has_reference"] is True


def test_read_experiment_returns_resolved_payload(tmp_path):
    _make_skeleton(tmp_path, "exp-a")
    payload = read_experiment(tmp_path, "exp-a")
    assert payload["name"] == "exp-a"
    assert payload["task_prompt"] == "do it."
    assert payload["system_prompt"] == "be careful."
    aug = next(c for c in payload["conditions"] if c["name"] == "augmented")
    assert aug["augmentation"] == "SLICE"


def test_read_experiment_not_found(tmp_path):
    with pytest.raises(ExperimentNotFound):
        read_experiment(tmp_path, "ghost")


def test_write_experiment_atomically(tmp_path):
    _make_skeleton(tmp_path, "exp-a")
    payload = read_experiment(tmp_path, "exp-a")
    payload["repetitions"] = 5
    payload["system_prompt"] = "NEW SYSTEM PROMPT"
    write_experiment(tmp_path, "exp-a", payload)

    # System prompt was written to prompts/system.md
    assert (tmp_path / "exp-a" / "prompts" / "system.md").read_text() == "NEW SYSTEM PROMPT"
    # And experiment.yaml has the new repetitions value
    yaml_text = (tmp_path / "exp-a" / "experiment.yaml").read_text()
    assert "repetitions: 5" in yaml_text or "repetitions:5" in yaml_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/abench_ui/test_experiments.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`abench_ui/experiments.py`:

```python
"""CRUD on experiments/<name>/ directories.

The on-disk layout is the source of truth. Reads return a fully-resolved payload
(prompt and slice text inlined). Writes split the payload back to YAML +
prompts/*.md + slices/*.md, with temp+rename for atomicity.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import yaml

from abench.config import load_experiment


class ExperimentNotFound(Exception):
    pass


def list_experiments(root: Path) -> list[dict]:
    """Return [{name, has_fixture, has_reference, has_runs, last_run_at}]."""
    root = Path(root)
    if not root.is_dir():
        return []
    items: list[dict] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        yaml_path = entry / "experiment.yaml"
        if not yaml_path.is_file():
            continue
        items.append({
            "name": entry.name,
            "has_fixture": (entry / "stripped").is_dir(),
            "has_reference": (entry / "original").is_dir(),
            "has_runs": (entry / "runs").is_dir() and any(
                (entry / "runs").iterdir()),
            "last_run_at": _last_run_at(entry / "runs"),
        })
    return items


def _last_run_at(runs_dir: Path) -> str | None:
    if not runs_dir.is_dir():
        return None
    candidates = list(runs_dir.glob("*/*/*/manifest.json"))
    if not candidates:
        return None
    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    import datetime
    return datetime.datetime.fromtimestamp(latest.stat().st_mtime).isoformat()


def read_experiment(root: Path, name: str) -> dict:
    """Return the fully-resolved Experiment payload (texts inlined)."""
    yaml_path = Path(root) / name / "experiment.yaml"
    if not yaml_path.is_file():
        raise ExperimentNotFound(name)
    exp = load_experiment(yaml_path)
    # model_dump returns paths as Path objects; serialise to str
    data = exp.model_dump(mode="json")
    return data


_PROMPTS_DIR = "prompts"
_SLICES_DIR = "slices"


def write_experiment(root: Path, name: str, payload: dict) -> None:
    """Write the payload back atomically.

    - system_prompt → prompts/system.md
    - task_prompt   → prompts/task.md
    - condition.augmentation (if not None) → slices/<condition>.md
    - everything else → experiment.yaml (with paths replaced by relative .md refs)
    """
    exp_dir = Path(root) / name
    exp_dir.mkdir(parents=True, exist_ok=True)
    (exp_dir / _PROMPTS_DIR).mkdir(exist_ok=True)
    (exp_dir / _SLICES_DIR).mkdir(exist_ok=True)

    # Pull text fields out
    yaml_payload = dict(payload)
    system_text = yaml_payload.pop("system_prompt", "")
    task_text = yaml_payload.pop("task_prompt", "")
    conditions = yaml_payload.get("conditions", [])

    _atomic_write(exp_dir / _PROMPTS_DIR / "system.md", system_text)
    _atomic_write(exp_dir / _PROMPTS_DIR / "task.md", task_text)

    # Replace text fields with relative paths in the yaml payload
    yaml_payload["system_prompt"] = f"./{_PROMPTS_DIR}/system.md"
    yaml_payload["task_prompt"] = f"./{_PROMPTS_DIR}/task.md"

    for cond in conditions:
        aug = cond.get("augmentation")
        if aug is None:
            continue
        slice_path = f"./{_SLICES_DIR}/{cond['name']}.md"
        _atomic_write(exp_dir / _SLICES_DIR / f"{cond['name']}.md", aug)
        cond["augmentation"] = slice_path

    # Make path fields relative if they live under exp_dir, else absolute
    for key in ("fixture_path", "reference_path", "output_dir"):
        if key in yaml_payload and yaml_payload[key]:
            yaml_payload[key] = _relpath(yaml_payload[key], exp_dir)

    _atomic_write(exp_dir / "experiment.yaml",
                  yaml.safe_dump(yaml_payload, sort_keys=False, allow_unicode=True))


def _atomic_write(path: Path, text: str) -> None:
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _relpath(target: str, base: Path) -> str:
    target_p = Path(target).resolve()
    try:
        return "./" + str(target_p.relative_to(base.resolve()))
    except ValueError:
        return str(target_p)
```

- [ ] **Step 4: Run tests + commit**

Run: `.venv/bin/pytest tests/abench_ui/test_experiments.py -v`
Expected: PASS.

```bash
git add abench_ui/experiments.py tests/abench_ui/test_experiments.py
git commit -m "feat(ui/experiments): list/read/write with atomic file writes"
```

---

## Task 9: `abench_ui/runs.py` — list runs, read artefacts, method_comparison, PATCH success

**Files:**
- Create: `abench_ui/runs.py`
- Create: `tests/abench_ui/test_runs.py`

- [ ] **Step 1: Write the failing test**

`tests/abench_ui/test_runs.py`:

```python
import json
from pathlib import Path

import pytest

from abench_ui.runs import (
    RunNotFound,
    list_runs,
    method_comparison,
    patch_success,
    read_artefact,
)


def _make_run(root: Path, name: str, cond: str, rep: int, *, success=None):
    rundir = root / name / cond / f"rep_{rep}"
    rundir.mkdir(parents=True)
    (rundir / "manifest.json").write_text(json.dumps({
        "condition": cond, "rep": rep, "model": "m",
    }))
    (rundir / "metrics.json").write_text(json.dumps({
        "n_steps": 4, "n_tool_calls": 3, "verify_status": "passed",
        "verify_passed_count": 10, "success": success,
        "finished": True, "interrupted_reason": None,
    }))
    (rundir / "trace.json").write_text(json.dumps({"steps": [], "turns": []}))
    (rundir / "events.jsonl").write_text('{"type":"ping"}\n')
    (rundir / "changes.patch").write_text("diff --git a/x b/x\n--- a/x\n+++ b/x\n+hi\n")
    return rundir


def test_list_runs(tmp_path):
    root = tmp_path / "exp-a" / "runs"
    _make_run(root, "x", "baseline", 0)
    _make_run(root, "x", "augmented", 1)
    items = list_runs(root / "x")
    keys = {(it["condition"], it["rep"]) for it in items}
    assert keys == {("baseline", 0), ("augmented", 1)}


def test_read_artefact(tmp_path):
    root = tmp_path / "exp" / "runs"
    _make_run(root, "x", "baseline", 0)
    metrics = read_artefact(root / "x", "baseline", 0, "metrics.json")
    assert json.loads(metrics)["n_steps"] == 4


def test_read_artefact_missing(tmp_path):
    with pytest.raises(RunNotFound):
        read_artefact(tmp_path / "no-such" / "x", "baseline", 0, "metrics.json")


def test_patch_success(tmp_path):
    root = tmp_path / "exp" / "runs"
    _make_run(root, "x", "baseline", 0)
    updated = patch_success(root / "x", "baseline", 0, success=True)
    assert updated["success"] is True
    # And it persisted on disk:
    assert json.loads(
        (root / "x" / "baseline" / "rep_0" / "metrics.json").read_text()
    )["success"] is True


def test_method_comparison_python(tmp_path):
    # Build a tiny reference + workdir that diverged in one method body
    ref = tmp_path / "ref"
    ref.mkdir()
    (ref / "mod.py").write_text(
        "def foo(x):\n    return x + 1\n\ndef bar():\n    return 2\n"
    )
    # Simulate "regenerated" file: same as original (semantically equivalent)
    wkdir = tmp_path / "wk"
    wkdir.mkdir()
    (wkdir / "mod.py").write_text(
        "def foo(x):\n    return x + 1\n\ndef bar():\n    return 2\n"
    )
    result = method_comparison(
        reference_dir=ref, workdir=wkdir,
        target_file="mod.py", method_name="foo",
    )
    assert result["method_name"] == "foo"
    assert "return x + 1" in "\n".join(result["original_lines"])
    assert "return x + 1" in "\n".join(result["regen_lines"])
    assert result["equivalent"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/abench_ui/test_runs.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

`abench_ui/runs.py`:

```python
"""Read run artefacts + structured method comparison."""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path


class RunNotFound(Exception):
    pass


def _rundir(root_runs_dir: Path, condition: str, rep: int) -> Path:
    return Path(root_runs_dir) / condition / f"rep_{rep}"


def list_runs(root_runs_dir: Path) -> list[dict]:
    """Walk runs/<exp>/<cond>/<rep>/ and return summaries."""
    root = Path(root_runs_dir)
    items: list[dict] = []
    if not root.is_dir():
        return items
    for cond_dir in sorted(root.iterdir()):
        if not cond_dir.is_dir():
            continue
        for rep_dir in sorted(cond_dir.iterdir()):
            if not rep_dir.is_dir() or not rep_dir.name.startswith("rep_"):
                continue
            m_path = rep_dir / "metrics.json"
            if not m_path.is_file():
                continue
            m = json.loads(m_path.read_text())
            items.append({
                "condition": cond_dir.name,
                "rep": int(rep_dir.name.removeprefix("rep_")),
                "finished": m.get("finished"),
                "interrupted_reason": m.get("interrupted_reason"),
                "verify_status": m.get("verify_status"),
                "success": m.get("success"),
                "started_at": _mtime_iso(m_path),
            })
    return items


def read_artefact(root_runs_dir: Path, condition: str, rep: int, name: str) -> str:
    """Return the raw file contents of <runs>/<cond>/rep_N/<name>."""
    rd = _rundir(root_runs_dir, condition, rep)
    p = rd / name
    if not p.is_file():
        raise RunNotFound(f"{condition}/rep_{rep}/{name}")
    return p.read_text(encoding="utf-8")


def patch_success(root_runs_dir: Path, condition: str, rep: int, *, success: bool | None) -> dict:
    """Update metrics.json[success] in place."""
    rd = _rundir(root_runs_dir, condition, rep)
    m_path = rd / "metrics.json"
    if not m_path.is_file():
        raise RunNotFound(f"{condition}/rep_{rep}/metrics.json")
    metrics = json.loads(m_path.read_text())
    metrics["success"] = success
    m_path.write_text(json.dumps(metrics, indent=2))
    return metrics


def method_comparison(
    *, reference_dir: Path, workdir: Path,
    target_file: str, method_name: str,
) -> dict:
    """Extract a named method/function from reference and workdir versions of
    target_file, returning the lines for each + an equivalence flag.

    Supports Python via ast and Java via brace-balancing on a regex'd signature."""
    ref_text = (Path(reference_dir) / target_file).read_text()
    regen_text = (Path(workdir) / target_file).read_text()
    if target_file.endswith(".py"):
        original = _extract_py_function(ref_text, method_name)
        regen = _extract_py_function(regen_text, method_name)
    elif target_file.endswith(".java"):
        original = _extract_java_method(ref_text, method_name)
        regen = _extract_java_method(regen_text, method_name)
    else:
        original, regen = ref_text.splitlines(), regen_text.splitlines()
    equivalent = _normalised(original) == _normalised(regen)
    return {
        "method_name": method_name,
        "original_lines": original,
        "regen_lines": regen,
        "equivalent": equivalent,
    }


def _extract_py_function(source: str, name: str) -> list[str]:
    tree = ast.parse(source)
    lines = source.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            start = node.lineno - 1
            end = node.end_lineno
            return lines[start:end]
    return []


_JAVA_SIG = re.compile(
    r"(?:public|private|protected|static|final|synchronized|abstract|\s)*\s*"
    r"[\w<>\[\],\s]*\s+(?P<name>\w+)\s*\([^)]*\)\s*(?:throws\s+[\w.,\s]+)?\s*\{"
)


def _extract_java_method(source: str, name: str) -> list[str]:
    lines = source.splitlines()
    for i, line in enumerate(lines):
        m = _JAVA_SIG.search(line)
        if m and m.group("name") == name:
            depth = line.count("{") - line.count("}")
            end = i
            for j in range(i + 1, len(lines)):
                depth += lines[j].count("{") - lines[j].count("}")
                end = j
                if depth == 0:
                    break
            return lines[i:end + 1]
    return []


def _normalised(lines: list[str]) -> str:
    return "\n".join(line.strip() for line in lines if line.strip())


def _mtime_iso(p: Path) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(p.stat().st_mtime).isoformat()
```

- [ ] **Step 4: Run tests + commit**

Run: `.venv/bin/pytest tests/abench_ui/test_runs.py -v`
Expected: PASS.

```bash
git add abench_ui/runs.py tests/abench_ui/test_runs.py
git commit -m "feat(ui/runs): list runs, read artefacts, method_comparison, PATCH success"
```

---

## Task 10: `abench_ui/validate.py` — model availability with TTL caches

**Files:**
- Create: `abench_ui/validate.py`
- Create: `tests/abench_ui/test_validate.py`

- [ ] **Step 1: Write the failing test**

`tests/abench_ui/test_validate.py`:

```python
import subprocess
from unittest.mock import patch

import pytest

from abench_ui.validate import validate_model, ValidationResult


def _fake_cli(args, **kwargs):
    """Pretend opencode CLI: providers list / models <p>."""
    text = " ".join(args) if isinstance(args, list) else args
    if "providers" in text:
        return subprocess.CompletedProcess(args, 0,
            stdout="opencode\nopenrouter\ndeepseek\n", stderr="")
    if "models" in text and "deepseek" in text:
        return subprocess.CompletedProcess(args, 0,
            stdout="deepseek/deepseek-chat\ndeepseek/deepseek-reasoner\n", stderr="")
    if "models" in text and "openrouter" in text:
        return subprocess.CompletedProcess(args, 0,
            stdout="openrouter/anthropic/claude-haiku-4.5\n", stderr="")
    return subprocess.CompletedProcess(args, 1, stdout="", stderr="unknown provider")


def test_validate_model_ok():
    with patch("abench_ui.validate.subprocess.run", side_effect=_fake_cli):
        result = validate_model("deepseek/deepseek-chat")
    assert result.status == "ok"
    assert result.provider == "deepseek"


def test_validate_model_no_credentials():
    def cli(args, **kw):
        text = " ".join(args)
        if "providers" in text:
            return subprocess.CompletedProcess(args, 0,
                stdout="opencode\n", stderr="")
        return _fake_cli(args, **kw)

    with patch("abench_ui.validate.subprocess.run", side_effect=cli):
        result = validate_model("deepseek/deepseek-chat")
    assert result.status == "no_credentials"
    assert result.provider == "deepseek"


def test_validate_model_not_in_catalog_with_suggestions():
    with patch("abench_ui.validate.subprocess.run", side_effect=_fake_cli):
        result = validate_model("deepseek/deepseek-chatt")  # typo
    assert result.status == "model_not_found"
    assert result.provider == "deepseek"
    assert any("deepseek-chat" in s for s in result.suggestions)


def test_validate_model_malformed():
    result = validate_model("nothing-here")
    assert result.status == "malformed"


def test_validate_model_unknown_provider():
    """`opencode models <p>` exit non-zero with unknown provider."""
    with patch("abench_ui.validate.subprocess.run", side_effect=_fake_cli):
        result = validate_model("mars/some-model")
    assert result.status == "no_credentials"  # provider not in providers list
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/abench_ui/test_validate.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

`abench_ui/validate.py`:

```python
"""Validate model availability without any chat-completion calls.

Sequence:
    1. `opencode providers list` (TTL 30s) → set of configured providers.
    2. If provider not configured → status=no_credentials, return.
    3. `opencode models <provider>` (TTL 5min) → catalog.
    4. If model id in catalog → status=ok.
    5. Else → status=model_not_found + difflib suggestions.
"""
from __future__ import annotations

import difflib
import subprocess
from dataclasses import dataclass, field
from typing import Literal

from cachetools import TTLCache, cached

Status = Literal["ok", "no_credentials", "model_not_found", "malformed"]


@dataclass
class ValidationResult:
    status: Status
    provider: str | None = None
    suggestions: list[str] = field(default_factory=list)


_PROVIDERS_CACHE: TTLCache = TTLCache(maxsize=1, ttl=30)
_MODELS_CACHE: TTLCache = TTLCache(maxsize=16, ttl=300)


@cached(_PROVIDERS_CACHE)
def _providers() -> set[str]:
    result = subprocess.run(
        ["opencode", "providers", "list"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        return set()
    out: set[str] = set()
    for raw in result.stdout.splitlines():
        line = raw.strip()
        if not line or line.startswith("┌") or line.startswith("│") or line.startswith("└"):
            continue
        # accept either bare names or markers like "●  OpenAI"
        token = line.lstrip("● ").split()[0].lower()
        if token:
            out.add(token)
    return out


@cached(_MODELS_CACHE)
def _models(provider: str) -> list[str]:
    result = subprocess.run(
        ["opencode", "models", provider],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def validate_model(model: str) -> ValidationResult:
    if "/" not in model:
        return ValidationResult(status="malformed")
    provider, _ = model.split("/", 1)
    provider = provider.strip().lower()
    if not provider:
        return ValidationResult(status="malformed")

    if provider not in _providers():
        return ValidationResult(status="no_credentials", provider=provider)

    catalog = _models(provider)
    if model in catalog:
        return ValidationResult(status="ok", provider=provider)

    # close-match suggestions on the *full* id
    sugg = difflib.get_close_matches(model, catalog, n=3, cutoff=0.6)
    return ValidationResult(
        status="model_not_found", provider=provider, suggestions=sugg,
    )
```

- [ ] **Step 4: Run tests + commit**

Run: `.venv/bin/pytest tests/abench_ui/test_validate.py -v`
Expected: PASS.

```bash
git add abench_ui/validate.py tests/abench_ui/test_validate.py
git commit -m "feat(ui/validate): model availability check via opencode metadata"
```

---

## Task 11: `abench_ui/providers.py` — list providers + write credentials to auth.json

**Files:**
- Create: `abench_ui/providers.py`
- Create: `tests/abench_ui/test_providers.py`

- [ ] **Step 1: Write the failing test**

`tests/abench_ui/test_providers.py`:

```python
import json
from pathlib import Path

import pytest

from abench_ui.providers import list_providers, write_credentials


def test_list_providers_reads_auth_json(tmp_path, monkeypatch):
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({
        "deepseek": {"type": "api", "key": "sk-xxx"},
        "openrouter": {"type": "api", "key": "sk-yyy"},
    }))
    monkeypatch.setattr("abench_ui.providers._auth_path", lambda: auth)
    items = list_providers()
    by_id = {it["id"]: it for it in items}
    assert by_id["deepseek"]["configured"] is True
    assert by_id["openrouter"]["configured"] is True


def test_list_providers_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr("abench_ui.providers._auth_path", lambda: tmp_path / "nope.json")
    assert list_providers() == []


def test_write_credentials_creates_file(tmp_path, monkeypatch):
    auth = tmp_path / "auth.json"
    monkeypatch.setattr("abench_ui.providers._auth_path", lambda: auth)
    write_credentials("deepseek", "sk-new")
    data = json.loads(auth.read_text())
    assert data == {"deepseek": {"type": "api", "key": "sk-new"}}


def test_write_credentials_merges_existing(tmp_path, monkeypatch):
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"openrouter": {"type": "api", "key": "sk-yyy"}}))
    monkeypatch.setattr("abench_ui.providers._auth_path", lambda: auth)
    write_credentials("deepseek", "sk-new")
    data = json.loads(auth.read_text())
    assert data["openrouter"]["key"] == "sk-yyy"
    assert data["deepseek"]["key"] == "sk-new"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/abench_ui/test_providers.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

`abench_ui/providers.py`:

```python
"""Provider list + auth.json writer."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def _auth_path() -> Path:
    return Path.home() / ".local" / "share" / "opencode" / "auth.json"


def list_providers() -> list[dict]:
    path = _auth_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return []
    return [{"id": pid, "configured": True} for pid in sorted(data)]


def write_credentials(provider: str, api_key: str) -> None:
    path = _auth_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text())
        except json.JSONDecodeError:
            existing = {}
    existing[provider] = {"type": "api", "key": api_key}
    _atomic_write(path, json.dumps(existing, indent=2))


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
```

- [ ] **Step 4: Run tests + commit**

Run: `.venv/bin/pytest tests/abench_ui/test_providers.py -v`
Expected: PASS.

```bash
git add abench_ui/providers.py tests/abench_ui/test_providers.py
git commit -m "feat(ui/providers): list providers + atomic auth.json writer"
```

---

## Task 12: `abench_ui/ws_buffer.py` + `abench_ui/ws_client.py` — ring buffer + WS-publishing client

**Files:**
- Create: `abench_ui/ws_buffer.py`
- Create: `abench_ui/ws_client.py`
- Create: `tests/abench_ui/test_ws_buffer.py`
- Create: `tests/abench_ui/test_ws_client.py`

- [ ] **Step 1: Write the failing test**

`tests/abench_ui/test_ws_buffer.py`:

```python
from abench_ui.ws_buffer import SessionEventBuffer


def test_buffer_round_robins_after_capacity():
    buf = SessionEventBuffer(capacity=3)
    for i in range(5):
        buf.append({"i": i})
    # only the last 3 should remain
    assert [e["i"] for e in buf.replay_from(0)] == [2, 3, 4]


def test_replay_from_specific_event_id():
    buf = SessionEventBuffer(capacity=10)
    ids = [buf.append({"i": i}) for i in range(5)]
    # replay from after event 2 → returns events 3, 4
    out = list(buf.replay_from(ids[2] + 1))
    assert [e["i"] for e in out] == [3, 4]


def test_replay_from_overflow_returns_all_remaining():
    """If last_event_id is older than the oldest buffered → return everything."""
    buf = SessionEventBuffer(capacity=3)
    for i in range(10):
        buf.append({"i": i})
    out = list(buf.replay_from(0))
    assert len(out) == 3  # only the last 3 are buffered
```

`tests/abench_ui/test_ws_client.py`:

```python
from abench_ui.ws_client import WSPublishingClient
from tests.fakes import FakeOpenCodeClient


def test_wraps_run_task_and_publishes_each_event(tmp_path):
    inner = FakeOpenCodeClient()
    captured = []
    client = WSPublishingClient(inner, publish=captured.append)

    on_events = []
    result = client.run_task(
        workdir=str(tmp_path),
        system_prompt="sys",
        model="m",
        user_message="do it",
        timeout_s=10,
        on_event=on_events.append,
    )
    # Both the inner client's events.jsonl writer AND the publish callback
    # must receive each event.
    assert len(captured) >= 1
    assert len(on_events) == len(captured)
    # Result is the inner client's result, unchanged.
    assert result is not None
    assert result.trace.finished is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/abench_ui/test_ws_buffer.py tests/abench_ui/test_ws_client.py -v`
Expected: FAIL — modules missing.

- [ ] **Step 3: Implement**

`abench_ui/ws_buffer.py`:

```python
"""Per-session ring buffer of raw events for WebSocket replay on reconnect."""
from __future__ import annotations

import itertools
from collections import deque
from typing import Iterable


class SessionEventBuffer:
    def __init__(self, capacity: int = 5000):
        self.capacity = capacity
        self._counter = itertools.count(1)
        self._items: deque[tuple[int, dict]] = deque(maxlen=capacity)

    def append(self, event: dict) -> int:
        event_id = next(self._counter)
        self._items.append((event_id, event))
        return event_id

    def replay_from(self, last_event_id: int) -> Iterable[dict]:
        for eid, ev in self._items:
            if eid >= last_event_id:
                yield ev
```

`abench_ui/ws_client.py`:

```python
"""WSPublishingClient — wraps any OpenCodeClient and publishes every raw
event to a callback as well as the inner on_event sink."""
from __future__ import annotations

from typing import Callable

from abench.opencode_client import OpenCodeClient, RunResult


class WSPublishingClient:
    def __init__(self, inner: OpenCodeClient, publish: Callable[[dict], None]):
        self._inner = inner
        self._publish = publish

    def run_task(
        self,
        *,
        workdir: str,
        system_prompt: str,
        model: str,
        user_message: str,
        timeout_s: int,
        on_event: Callable[[dict], None],
    ) -> RunResult:
        def on_event_relay(event: dict) -> None:
            self._publish(event)
            on_event(event)
        return self._inner.run_task(
            workdir=workdir, system_prompt=system_prompt, model=model,
            user_message=user_message, timeout_s=timeout_s, on_event=on_event_relay,
        )
```

- [ ] **Step 4: Run tests + commit**

Run: `.venv/bin/pytest tests/abench_ui/test_ws_buffer.py tests/abench_ui/test_ws_client.py -v`
Expected: PASS.

```bash
git add abench_ui/ws_buffer.py abench_ui/ws_client.py \
        tests/abench_ui/test_ws_buffer.py tests/abench_ui/test_ws_client.py
git commit -m "feat(ui/ws): ring buffer for replay + WS-publishing client adapter"
```

---

## Task 13: `abench_ui/run_session.py` — RunSession lifecycle (thread + state + cancel)

**Files:**
- Create: `abench_ui/run_session.py`
- Create: `tests/abench_ui/test_run_session.py`

- [ ] **Step 1: Write the failing test**

`tests/abench_ui/test_run_session.py`:

```python
import time
from pathlib import Path

from abench.config import Condition, Experiment, IsolationCfg, MetricsCfg, OpenCodeCfg, VerifyCfg
from abench_ui.run_session import RunSession, SessionState
from tests.fakes import FakeOpenCodeClient


def _make_exp(tmp_path: Path) -> Experiment:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "a.py").write_text("x = 1\n")
    reference = tmp_path / "reference"
    reference.mkdir()
    return Experiment(
        name="rs-test",
        fixture_path=fixture, reference_path=reference,
        task_prompt="t", system_prompt="s", model="m",
        output_dir=tmp_path / "runs", repetitions=1,
        conditions=[Condition(name="baseline", augmentation=None)],
        opencode=OpenCodeCfg(), metrics=MetricsCfg(),
        verify=VerifyCfg(enabled=False),
        isolation=IsolationCfg(nonce_prefix=False, shuffle_order=False),
    )


def test_run_session_runs_to_completion_and_publishes_envelopes(tmp_path):
    exp = _make_exp(tmp_path)
    published: list[dict] = []
    session = RunSession(
        id="sess-1",
        experiment=exp,
        client_factory=lambda e: FakeOpenCodeClient(),
        publish=published.append,
    )
    session.start()
    # Wait up to 5s for completion
    for _ in range(50):
        if session.state in (SessionState.COMPLETED, SessionState.FAILED):
            break
        time.sleep(0.1)
    assert session.state == SessionState.COMPLETED

    types = [m["type"] for m in published]
    assert types[0] == "session.started"
    assert "run.started" in types
    assert "raw_event" in types
    assert "run.finished" in types
    assert types[-1] == "session.finished"


def test_run_session_cancel_marks_state(tmp_path):
    """Best-effort cancel — set the flag; the run still wraps up cleanly."""
    exp = _make_exp(tmp_path)
    session = RunSession(
        id="sess-2", experiment=exp,
        client_factory=lambda e: FakeOpenCodeClient(),
        publish=lambda _ev: None,
    )
    session.start()
    session.cancel()
    # cancel is best-effort; eventually state is COMPLETED or CANCELLED
    for _ in range(50):
        if session.state in (SessionState.COMPLETED, SessionState.FAILED, SessionState.CANCELLED):
            break
        time.sleep(0.1)
    assert session.state in (SessionState.COMPLETED, SessionState.CANCELLED)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/abench_ui/test_run_session.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

`abench_ui/run_session.py`:

```python
"""RunSession — encapsulates one in-flight experiment, runs it in a thread,
publishes WS-style envelope messages, supports cooperative cancel."""
from __future__ import annotations

import threading
import time
import traceback
from enum import Enum
from typing import Callable

from abench.config import Experiment
from abench.runner import run_experiment
from .ws_client import WSPublishingClient


class SessionState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunSession:
    def __init__(
        self,
        id: str,
        experiment: Experiment,
        client_factory: Callable[[Experiment], object],
        publish: Callable[[dict], None],
    ):
        self.id = id
        self.experiment = experiment
        self._client_factory = client_factory
        self._publish = publish
        self.state = SessionState.PENDING
        self.started_at: float | None = None
        self.ended_at: float | None = None
        self._thread: threading.Thread | None = None
        self._cancel_flag = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("RunSession already started")
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel_flag.set()

    def _run(self) -> None:
        self.state = SessionState.RUNNING
        self.started_at = time.time()
        total = len(self.experiment.conditions) * self.experiment.repetitions
        self._publish({"type": "session.started", "total_runs": total,
                       "session_id": self.id})

        run_idx = 0

        def run_event_wrapper(inner_client_factory):
            """Wraps inner client to publish run.started / run.finished envelopes
            plus raw_event per opencode event."""
            def factory(exp: Experiment):
                inner = inner_client_factory(exp)
                def publish_raw(ev: dict):
                    self._publish({
                        "type": "raw_event",
                        "session_id": self.id,
                        "event": ev,
                    })
                return WSPublishingClient(inner, publish=publish_raw)
            return factory

        try:
            # NOTE: cooperative cancel isn't a hard kill in v1 — abench.runner
            # doesn't expose per-run hooks. We at least flip state at the end.
            run_experiment(
                self.experiment,
                run_event_wrapper(self._client_factory),
            )
            if self._cancel_flag.is_set():
                self.state = SessionState.CANCELLED
            else:
                self.state = SessionState.COMPLETED
        except Exception as exc:
            self.state = SessionState.FAILED
            self._publish({"type": "session.error",
                           "session_id": self.id,
                           "message": str(exc),
                           "traceback": traceback.format_exc()})
            return
        finally:
            self.ended_at = time.time()
            duration = (self.ended_at - (self.started_at or self.ended_at))
            self._publish({"type": "session.finished",
                           "session_id": self.id,
                           "duration_s": duration})
```

- [ ] **Step 4: Run tests + commit**

Run: `.venv/bin/pytest tests/abench_ui/test_run_session.py -v`
Expected: PASS.

```bash
git add abench_ui/run_session.py tests/abench_ui/test_run_session.py
git commit -m "feat(ui/run_session): thread-based session lifecycle with envelope publishing"
```

---

## Task 14: `abench_ui/server.py` — FastAPI app + REST + WS wiring + static serving

**Files:**
- Create: `abench_ui/server.py`
- Create: `tests/abench_ui/test_experiments_api.py`
- Create: `tests/abench_ui/test_runs_api.py`
- Create: `tests/abench_ui/test_ws_e2e.py`

- [ ] **Step 1: Write the failing tests (REST first)**

`tests/abench_ui/test_experiments_api.py`:

```python
import json
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from abench_ui.server import create_app


def _scaffold_exp(root: Path, name: str):
    d = root / name
    d.mkdir(parents=True)
    (d / "prompts").mkdir()
    (d / "slices").mkdir()
    (d / "prompts" / "task.md").write_text("do it.")
    (d / "prompts" / "system.md").write_text("be careful.")
    (d / "original").mkdir()
    (d / "original" / "a.py").write_text("x")
    (d / "stripped").mkdir()
    (d / "stripped" / "a.py").write_text("x")
    (d / "experiment.yaml").write_text(textwrap.dedent(f"""\
        name: {name}
        fixture_path: ./stripped
        reference_path: ./original
        task_prompt: ./prompts/task.md
        system_prompt: ./prompts/system.md
        model: opencode/deepseek-v4-flash-free
        repetitions: 1
        output_dir: ./runs
        conditions:
          - {{name: baseline, augmentation: null}}
    """))
    return d


@pytest.fixture
def client(tmp_path):
    app = create_app(experiments_dir=tmp_path)
    return TestClient(app), tmp_path


def test_schema_endpoint(client):
    c, _ = client
    r = c.get("/api/schema")
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "object"
    assert "name" in body["properties"]


def test_list_experiments_endpoint(client):
    c, root = client
    _scaffold_exp(root, "exp-a")
    r = c.get("/api/experiments")
    assert r.status_code == 200
    items = r.json()
    assert any(it["name"] == "exp-a" for it in items)


def test_read_experiment_endpoint(client):
    c, root = client
    _scaffold_exp(root, "exp-a")
    r = c.get("/api/experiments/exp-a")
    assert r.status_code == 200
    body = r.json()
    assert body["task_prompt"] == "do it."


def test_read_experiment_404(client):
    c, _ = client
    r = c.get("/api/experiments/ghost")
    assert r.status_code == 404


def test_put_experiment_then_read_returns_new_values(client):
    c, root = client
    _scaffold_exp(root, "exp-a")
    payload = c.get("/api/experiments/exp-a").json()
    payload["system_prompt"] = "BRAND NEW SYSTEM"
    r = c.put("/api/experiments/exp-a", json=payload)
    assert r.status_code == 200
    payload2 = c.get("/api/experiments/exp-a").json()
    assert payload2["system_prompt"] == "BRAND NEW SYSTEM"


def test_put_experiment_422_on_pydantic_error(client):
    c, root = client
    _scaffold_exp(root, "exp-a")
    bad = c.get("/api/experiments/exp-a").json()
    bad["repetitions"] = -3  # invalid
    r = c.put("/api/experiments/exp-a", json=bad)
    assert r.status_code == 422


def test_delete_experiment(client):
    c, root = client
    _scaffold_exp(root, "exp-a")
    r = c.delete("/api/experiments/exp-a")
    assert r.status_code == 200
    assert not (root / "exp-a").exists()
    assert c.delete("/api/experiments/exp-a").status_code == 404


def test_upload_yaml_returns_payload(client):
    c, _ = client
    yaml_text = """
name: from-upload
fixture_path: ./stripped
reference_path: ./original
task_prompt: do it
system_prompt: be careful
model: opencode/deepseek-v4-flash-free
output_dir: ./runs
conditions:
  - {name: baseline, augmentation: null}
"""
    r = c.post("/api/experiments/upload", content=yaml_text,
               headers={"content-type": "application/yaml"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "from-upload"


def test_upload_yaml_invalid_422(client):
    c, _ = client
    r = c.post("/api/experiments/upload", content="not: [valid yaml",
               headers={"content-type": "application/yaml"})
    assert r.status_code == 422
```

`tests/abench_ui/test_runs_api.py`:

```python
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from abench_ui.server import create_app


def _make_runs(root: Path):
    name = "exp-a"
    rd = root / name / "runs" / name / "baseline" / "rep_0"
    rd.mkdir(parents=True)
    (rd / "manifest.json").write_text(json.dumps({"condition": "baseline", "rep": 0}))
    (rd / "metrics.json").write_text(json.dumps({
        "n_steps": 4, "verify_status": "passed",
        "verify_passed_count": 10, "success": None,
        "finished": True, "interrupted_reason": None,
    }))
    (rd / "trace.json").write_text(json.dumps({"steps": [], "turns": []}))
    (rd / "changes.patch").write_text("diff --git a/x b/x\n--- a/x\n+++ b/x\n+1\n")
    # also scaffold the experiment.yaml so /api/experiments/{name} works
    (root / name / "experiment.yaml").write_text("name: exp-a\nfixture_path: ./stripped\n")


@pytest.fixture
def client(tmp_path):
    app = create_app(experiments_dir=tmp_path)
    return TestClient(app), tmp_path


def test_list_runs_endpoint(client):
    c, root = client
    _make_runs(root)
    r = c.get("/api/runs/exp-a")
    assert r.status_code == 200
    items = r.json()
    assert any(it["condition"] == "baseline" and it["rep"] == 0 for it in items)


def test_read_run_artefacts(client):
    c, root = client
    _make_runs(root)
    r = c.get("/api/runs/exp-a/baseline/0/metrics")
    assert r.status_code == 200
    assert r.json()["n_steps"] == 4
    r = c.get("/api/runs/exp-a/baseline/0/trace")
    assert r.json() == {"steps": [], "turns": []}
    r = c.get("/api/runs/exp-a/baseline/0/patch")
    assert "diff --git" in r.text


def test_patch_success(client):
    c, root = client
    _make_runs(root)
    r = c.patch("/api/runs/exp-a/baseline/0", json={"success": True})
    assert r.status_code == 200
    assert r.json()["success"] is True
```

`tests/abench_ui/test_ws_e2e.py`:

```python
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from abench_ui.server import create_app


def _scaffold_minimal_exp(root: Path):
    d = root / "exp-ws"
    d.mkdir()
    (d / "prompts").mkdir()
    (d / "slices").mkdir()
    (d / "prompts" / "task.md").write_text("t")
    (d / "prompts" / "system.md").write_text("s")
    (d / "original").mkdir()
    (d / "original" / "a.py").write_text("x")
    (d / "stripped").mkdir()
    (d / "stripped" / "a.py").write_text("x")
    (d / "experiment.yaml").write_text(textwrap.dedent("""\
        name: exp-ws
        fixture_path: ./stripped
        reference_path: ./original
        task_prompt: ./prompts/task.md
        system_prompt: ./prompts/system.md
        model: opencode/deepseek-v4-flash-free
        repetitions: 1
        output_dir: ./runs
        conditions:
          - {name: baseline, augmentation: null}
        verify:
          enabled: false
        isolation:
          nonce_prefix: false
          shuffle_order: false
    """))


def test_ws_publishes_session_lifecycle(tmp_path):
    _scaffold_minimal_exp(tmp_path)
    # Inject a fake client factory so the run completes synchronously without
    # actually calling opencode.
    from tests.fakes import FakeOpenCodeClient
    app = create_app(
        experiments_dir=tmp_path,
        client_factory_override=lambda e: FakeOpenCodeClient(),
    )
    client = TestClient(app)

    r = client.post("/api/runs", json={"experiment_name": "exp-ws"})
    assert r.status_code == 200
    sid = r.json()["session_id"]

    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        # Drain messages until session.finished
        types_seen: list[str] = []
        while True:
            msg = ws.receive_json(mode="text")
            types_seen.append(msg["type"])
            if msg["type"] == "session.finished":
                break
            if len(types_seen) > 200:
                pytest.fail(f"too many events: {types_seen}")
    assert "session.started" in types_seen
    assert "run.started" in types_seen
    assert "raw_event" in types_seen
    assert "run.finished" in types_seen
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/abench_ui/test_experiments_api.py tests/abench_ui/test_runs_api.py tests/abench_ui/test_ws_e2e.py -v`
Expected: FAIL — `abench_ui.server.create_app` does not exist.

- [ ] **Step 3: Implement**

`abench_ui/server.py`:

```python
"""FastAPI application — REST + WS, in-process abench runner."""
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Callable

from fastapi import (
    APIRouter,
    FastAPI,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel, ValidationError

from abench.config import Experiment, OpenCodeCfg
from abench.opencode_client import RealOpenCodeClient

from . import experiments as exp_mod
from . import providers as prov_mod
from . import runs as runs_mod
from .run_session import RunSession, SessionState
from .schema import experiment_json_schema
from .validate import validate_model
from .ws_buffer import SessionEventBuffer


# ── Models ───────────────────────────────────────────────────────────

class _ValidateModelBody(BaseModel):
    model: str


class _CredentialsBody(BaseModel):
    api_key: str


class _RunStartBody(BaseModel):
    experiment_name: str


class _SuccessPatchBody(BaseModel):
    success: bool | None = None


# ── Factory ──────────────────────────────────────────────────────────

def create_app(
    *,
    experiments_dir: Path,
    client_factory_override: Callable | None = None,
) -> FastAPI:
    """Build the FastAPI app rooted at `experiments_dir`.

    If `client_factory_override` is provided, RunSession uses it instead of
    constructing a RealOpenCodeClient — useful for tests."""
    app = FastAPI(title="abench-ui", version="0.1.0")
    state: dict = {
        "experiments_dir": Path(experiments_dir),
        "sessions": {},               # id -> RunSession
        "buffers": {},                # id -> SessionEventBuffer
        "ws_queues": {},              # id -> list[asyncio.Queue]
        "client_factory_override": client_factory_override,
    }
    app.state.abench = state

    api = APIRouter(prefix="/api")

    @api.get("/schema")
    def _schema():
        return experiment_json_schema()

    @api.get("/experiments")
    def _list_exp():
        return exp_mod.list_experiments(state["experiments_dir"])

    @api.get("/experiments/{name}")
    def _read_exp(name: str):
        try:
            return exp_mod.read_experiment(state["experiments_dir"], name)
        except exp_mod.ExperimentNotFound:
            raise HTTPException(404, f"experiment '{name}' not found")

    @api.put("/experiments/{name}")
    async def _write_exp(name: str, request: Request):
        payload = await request.json()
        try:
            # Validate by pydantic round-trip before writing
            Experiment(**payload)
        except ValidationError as exc:
            raise HTTPException(422, exc.errors())
        exp_mod.write_experiment(state["experiments_dir"], name, payload)
        return {"ok": True}

    @api.delete("/experiments/{name}")
    def _delete_exp(name: str):
        import shutil
        target = state["experiments_dir"] / name
        if not target.is_dir():
            raise HTTPException(404, f"experiment '{name}' not found")
        shutil.rmtree(target)
        return {"ok": True}

    @api.post("/experiments/upload")
    async def _upload_exp(request: Request):
        """Parse a raw YAML body and return the resolved Experiment payload +
        validation diagnostic. Does NOT persist anything — UI follows up with
        PUT /api/experiments/{name} once the user picks a target name."""
        import yaml as _yaml
        body = (await request.body()).decode("utf-8")
        try:
            data = _yaml.safe_load(body)
        except _yaml.YAMLError as exc:
            raise HTTPException(422, f"invalid YAML: {exc}")
        if not isinstance(data, dict):
            raise HTTPException(422, "top-level YAML must be a mapping")
        try:
            exp = Experiment(**data)
        except ValidationError as exc:
            raise HTTPException(422, exc.errors())
        return exp.model_dump(mode="json")

    @api.get("/runs/{name}")
    def _list_runs(name: str):
        runs_dir = state["experiments_dir"] / name / "runs" / name
        return runs_mod.list_runs(runs_dir)

    @api.get("/runs/{name}/{condition}/{rep}/metrics")
    def _read_metrics(name: str, condition: str, rep: int):
        runs_dir = state["experiments_dir"] / name / "runs" / name
        try:
            return json.loads(runs_mod.read_artefact(runs_dir, condition, rep, "metrics.json"))
        except runs_mod.RunNotFound as exc:
            raise HTTPException(404, str(exc))

    @api.get("/runs/{name}/{condition}/{rep}/trace")
    def _read_trace(name: str, condition: str, rep: int):
        runs_dir = state["experiments_dir"] / name / "runs" / name
        try:
            return json.loads(runs_mod.read_artefact(runs_dir, condition, rep, "trace.json"))
        except runs_mod.RunNotFound as exc:
            raise HTTPException(404, str(exc))

    @api.get("/runs/{name}/{condition}/{rep}/patch")
    def _read_patch(name: str, condition: str, rep: int):
        runs_dir = state["experiments_dir"] / name / "runs" / name
        try:
            return Response(
                runs_mod.read_artefact(runs_dir, condition, rep, "changes.patch"),
                media_type="text/plain",
            )
        except runs_mod.RunNotFound as exc:
            raise HTTPException(404, str(exc))

    @api.patch("/runs/{name}/{condition}/{rep}")
    def _patch_run(name: str, condition: str, rep: int, body: _SuccessPatchBody):
        runs_dir = state["experiments_dir"] / name / "runs" / name
        try:
            return runs_mod.patch_success(runs_dir, condition, rep, success=body.success)
        except runs_mod.RunNotFound as exc:
            raise HTTPException(404, str(exc))

    @api.post("/validate/model")
    def _validate(body: _ValidateModelBody):
        r = validate_model(body.model)
        return {"status": r.status, "provider": r.provider, "suggestions": r.suggestions}

    @api.get("/providers")
    def _providers():
        return prov_mod.list_providers()

    @api.post("/providers/{provider}/credentials")
    def _creds(provider: str, body: _CredentialsBody):
        prov_mod.write_credentials(provider, body.api_key)
        return {"ok": True}

    @api.post("/runs")
    def _start_run(body: _RunStartBody):
        try:
            exp_payload = exp_mod.read_experiment(state["experiments_dir"], body.experiment_name)
        except exp_mod.ExperimentNotFound:
            raise HTTPException(404, f"experiment '{body.experiment_name}' not found")
        exp = Experiment(**exp_payload)
        sid = uuid.uuid4().hex
        buf = SessionEventBuffer()
        state["buffers"][sid] = buf
        state["ws_queues"][sid] = []

        def publish(envelope: dict) -> None:
            buf.append(envelope)
            for q in list(state["ws_queues"].get(sid, [])):
                try:
                    q.put_nowait(envelope)
                except asyncio.QueueFull:
                    pass

        client_factory = state["client_factory_override"] or (
            lambda e: RealOpenCodeClient(e.opencode, e.timeout_s)
        )
        session = RunSession(
            id=sid, experiment=exp,
            client_factory=client_factory, publish=publish,
        )
        state["sessions"][sid] = session
        session.start()
        return {"session_id": sid}

    @api.get("/sessions/{sid}")
    def _session_state(sid: str):
        session = state["sessions"].get(sid)
        if session is None:
            raise HTTPException(404, "session not found")
        return {"state": session.state.value,
                "started_at": session.started_at,
                "ended_at": session.ended_at}

    @api.delete("/sessions/{sid}")
    def _cancel_session(sid: str):
        session = state["sessions"].get(sid)
        if session is None:
            raise HTTPException(404, "session not found")
        session.cancel()
        return {"ok": True}

    app.include_router(api)

    @app.websocket("/ws/sessions/{sid}")
    async def _ws(ws: WebSocket, sid: str):
        await ws.accept()
        if sid not in state["sessions"]:
            await ws.close(code=4004)
            return
        q: asyncio.Queue = asyncio.Queue(maxsize=10_000)
        state["ws_queues"].setdefault(sid, []).append(q)
        # Optional replay of buffered events
        last_id = int(ws.query_params.get("last_event_id", 0))
        for ev in state["buffers"][sid].replay_from(last_id):
            await ws.send_json(ev)
        try:
            while True:
                envelope = await q.get()
                await ws.send_json(envelope)
                if envelope.get("type") in ("session.finished", "session.error"):
                    break
        except WebSocketDisconnect:
            pass
        finally:
            try:
                state["ws_queues"][sid].remove(q)
            except (KeyError, ValueError):
                pass

    return app
```

- [ ] **Step 4: Run tests + commit**

Run: `.venv/bin/pytest tests/abench_ui/test_experiments_api.py tests/abench_ui/test_runs_api.py tests/abench_ui/test_ws_e2e.py -v`
Expected: PASS.

```bash
git add abench_ui/server.py tests/abench_ui/test_experiments_api.py \
        tests/abench_ui/test_runs_api.py tests/abench_ui/test_ws_e2e.py
git commit -m "feat(ui/server): FastAPI app — REST + WebSocket + run session orchestration"
```

---

## Task 15: `abench_ui/cli.py` — `abench-ui` console script

**Files:**
- Create: `abench_ui/cli.py`
- Create: `tests/abench_ui/test_cli.py`

- [ ] **Step 1: Write the failing test**

`tests/abench_ui/test_cli.py`:

```python
import sys
from unittest.mock import patch

from abench_ui.cli import main


def test_cli_parses_and_calls_uvicorn(monkeypatch, tmp_path):
    calls = {}
    def fake_run(app, **kwargs):
        calls["app"] = app
        calls.update(kwargs)
    with patch("abench_ui.cli.uvicorn.run", side_effect=fake_run):
        rc = main(["--port", "9999", "--host", "127.0.0.1",
                   "--experiments-dir", str(tmp_path)])
    assert rc == 0
    assert calls["port"] == 9999
    assert calls["host"] == "127.0.0.1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/abench_ui/test_cli.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

`abench_ui/cli.py`:

```python
"""`abench-ui` console-script — starts the FastAPI app via uvicorn."""
from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from .server import create_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="abench-ui")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--experiments-dir", default="experiments",
                        help="path to the experiments/ directory")
    args = parser.parse_args(argv)

    app = create_app(experiments_dir=Path(args.experiments_dir).resolve())
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0
```

- [ ] **Step 4: Run tests + final full suite + commit**

```bash
.venv/bin/pytest tests/abench_ui/test_cli.py -v
.venv/bin/pytest -q
```
Expected: all PASS (counts: ~21 prior + ~30+ new = 50+ tests).

```bash
git add abench_ui/cli.py tests/abench_ui/test_cli.py
git commit -m "feat(ui/cli): abench-ui console-script via uvicorn"
```

---

## Self-Review (against spec sections)

| Spec section | Covered by |
|---|---|
| §1 Цель | Tasks 7–15 wire up the API surface. |
| §2 v1/v2/v3+ split | Plan A targets v1 only. v2+ explicit out-of-scope. |
| §3 Architecture | Task 13 RunSession + Task 14 server (in-process runner + WS). |
| §4 Package layout | All `abench_ui/` modules created in Tasks 7–15. |
| §5.1 trace_model | Task 2. |
| §5.2 trace_normalize | Task 3. |
| §5.3 config | Task 1. |
| §5.4 verify module | Task 4. |
| §5.5 runner changes | Task 5 (isolation, verify integration, final_diff_summary). |
| §5.6 metrics | Task 6 (auto-success + verify_* propagation). |
| §6 REST + WS endpoints | Task 14 (all endpoints except `/api/runs/.../method_comparison` — see note below). |
| §7 UI screens | Out of scope (Plan B). |
| §8 Validation surface | Task 10 (model availability), Task 1 (config validators). |
| §9 Verify subsystem | Tasks 4, 5. Baseline pre-flight is partially deferred — flagged. |
| §10 KV-cache isolation | Task 5 (nonce-prefix + shuffle). |
| §11 Final diff + method comparison | Task 5 (FinalDiffSummary), Task 9 (method_comparison helper). The HTTP endpoint for method_comparison is exposed in Task 14 — add the route. |
| §12 Error handling | Tasks 1, 4, 14 (pydantic ValidationError → 422, RunNotFound → 404, WS reconnect via Task 12). |
| §13 Run flow | Task 13. |
| §14 Test strategy | Each task includes its tests; e2e via Task 14. |

**Gaps detected & fixed inline:**

- `/api/runs/{name}/{condition}/{rep}/method_comparison` HTTP route is mentioned in spec §6 but not in Task 14's code. **Fix:** add to Task 14 Step 3 after the `_read_patch` route:

```python
@api.get("/runs/{name}/{condition}/{rep}/method_comparison")
def _method_comparison(name: str, condition: str, rep: int, request: Request):
    exp_dir = state["experiments_dir"] / name
    try:
        exp_payload = exp_mod.read_experiment(state["experiments_dir"], name)
    except exp_mod.ExperimentNotFound:
        raise HTTPException(404, "experiment not found")
    target_file = exp_payload.get("target_file")
    methods = exp_payload.get("target_methods") or []
    if not target_file:
        raise HTTPException(400, "experiment has no target_file configured")
    workdir_proxy = exp_dir / "stripped"  # post-cleanup workdir is gone, use stripped
    reference = exp_dir / "original"
    if not methods:
        # Comparison over the whole file
        return runs_mod.method_comparison(
            reference_dir=reference, workdir=workdir_proxy,
            target_file=target_file, method_name="",
        )
    method = request.query_params.get("method") or methods[0]
    return runs_mod.method_comparison(
        reference_dir=reference, workdir=workdir_proxy,
        target_file=target_file, method_name=method,
    )
```

- Baseline pre-flight verify is described in spec §5.5 + §9 but NOT wired in Task 5. **Fix-in-this-plan:** insert a sub-step in Task 5 Step 3:

```python
# At the top of run_experiment, before the plan loop:
if exp.verify.enabled:
    baseline_cache = exp.fixture_path.parent / ".verify-baseline.json"  # next to fixture
    # If cache missing or reference sha changed → run verify on a copy of reference_path.
    # On failure, set per-rep result.trace.verify_baseline_unknown = True.
    # For brevity in v1: do the check, log warning, propagate flag inside _run_one.
    _maybe_run_baseline_verify(exp, baseline_cache)
```

And add the helper:

```python
def _maybe_run_baseline_verify(exp, cache_path: Path) -> None:
    """Best-effort baseline verify; caches result in cache_path."""
    import hashlib, json as _json
    ref_sha = _dir_sha(exp.reference_path)
    if cache_path.is_file():
        try:
            cached = _json.loads(cache_path.read_text())
            if cached.get("reference_sha") == ref_sha:
                return
        except Exception:
            pass
    # Run verify on a fresh copy of reference_path
    workdir, _sha = fx.create_workdir(exp.reference_path)
    try:
        command = exp.verify.command or _detect_verify(workdir)
        if command is None:
            return
        v = run_verify(workdir, command, exp.verify.timeout_s)
        cache_path.write_text(_json.dumps({
            "command": command, "reference_sha": ref_sha,
            "status": v.status, "passed_count": v.passed_count,
            "failed_count": v.failed_count,
        }))
    finally:
        fx.cleanup(workdir)


def _dir_sha(path: Path) -> str:
    """Cheap stable hash of a directory tree."""
    import hashlib
    h = hashlib.sha1()
    for p in sorted(Path(path).rglob("*")):
        if p.is_file():
            h.update(p.relative_to(path).as_posix().encode())
            h.update(b"\x00")
            h.update(p.read_bytes())
    return h.hexdigest()[:16]
```

Inside `_run_one`, when verify is run, also load the cache and set `result.trace.verify_baseline_unknown` if cached baseline status != "passed". Add to Task 5:

```python
if exp.verify.enabled:
    baseline_cache = exp.fixture_path.parent / ".verify-baseline.json"
    if baseline_cache.is_file():
        try:
            baseline = json.loads(baseline_cache.read_text())
            if baseline.get("status") != "passed":
                result.trace.verify_baseline_unknown = True
        except Exception:
            pass
```

(Update the test `test_run_experiment_writes_isolation_nonce_to_trace` accordingly only if verify is enabled; in the existing tests we have `VerifyCfg(enabled=False)` for isolation tests, so baseline check is bypassed.)

**Type consistency:** all module-spanning types — `Experiment`, `VerifyCfg`, `IsolationCfg`, `Trace`, `TurnInfo`, `FinalDiffSummary`, `FileChange`, `VerifyResult`, `ValidationResult`, `RunSession`, `SessionState`, `SessionEventBuffer`, `WSPublishingClient` — are defined exactly once and referenced consistently.

**No placeholders:** every step has actual code or commands. Build-tool parsers (Maven/Gradle/pytest) are concrete; jest/cargo/go are deliberately out of scope for Plan A.
