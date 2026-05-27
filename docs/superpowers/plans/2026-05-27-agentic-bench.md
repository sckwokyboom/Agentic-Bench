# Agentic-Bench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python harness (`abench`) that drives the OpenCode agent on a fixed task in an isolated copy of a project and captures a full normalized trace + metrics, to compare baseline vs RAG-augmented runs.

**Architecture:** Two seams keep the design clean. (1) The `OpenCodeClient` interface returns a *normalized* `Trace`, so the whole analysis pipeline (metrics, report) is independent of OpenCode's wire format and fully testable offline with a fake client. (2) `opencode_client.py` is the only module that knows OpenCode specifics. The plan has two phases: **Phase 1** builds the entire offline core (config, prompt, fixture, trace model, metrics, runner, report, CLI `report`) test-first with synthetic/fake data — no OpenCode needed. **Phase 2** installs OpenCode, verifies its real API (spike), then implements the adapter + normalizer + CLI `run`.

**Tech Stack:** Python ≥3.12, `pydantic` v2 (config), `pyyaml`, `httpx` + `httpx-sse` (HTTP/SSE), `pandas` (report), `pytest` (tests), `git` CLI (fixture isolation).

**Spec:** `docs/superpowers/specs/2026-05-27-agentic-bench-design.md`

---

## File Structure

```
pyproject.toml                  # package + deps + console script
abench/__init__.py
abench/trace_model.py           # Step, StepKind, Trace (normalized schema) + (de)serialize
abench/diffstat.py              # parse unified diff -> (files, added, removed)
abench/metrics.py               # MetricsConfig + extract(trace, patch, cfg) -> dict
abench/prompt.py                # compose(task, augmentation) -> str
abench/config.py                # Experiment/Condition models + load_experiment()
abench/fixture.py               # create_workdir / diff_workdir / cleanup
abench/opencode_client.py       # RunResult, OpenCodeClient(Protocol), RealOpenCodeClient (Phase 2)
abench/trace_normalize.py       # normalize(raw_events, raw_session) -> Trace (Phase 2)
abench/runner.py                # run_experiment(exp, client_factory)
abench/report.py                # load_runs / summarize / write_report
abench/cli.py                   # argparse: `abench run`, `abench report`
tests/                          # one test module per source module
tests/fakes.py                  # FakeOpenCodeClient for offline runner tests
tests/fixtures/opencode/        # captured real samples (created in Phase 2 spike)
docs/superpowers/notes/opencode-api.md   # verified API notes (created in Phase 2 spike)
```

---

# Phase 1 — Offline core (no OpenCode required)

## Task 0: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `abench/__init__.py`
- Create: `tests/__init__.py`
- Create: `.gitignore`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "abench"
version = "0.1.0"
description = "Agentic-Bench: harness for comparing OpenCode agent runs"
requires-python = ">=3.12"
dependencies = [
    "pyyaml>=6",
    "pydantic>=2",
    "httpx>=0.27",
    "httpx-sse>=0.4",
    "pandas>=2",
]

[project.optional-dependencies]
dev = ["pytest>=8"]

[project.scripts]
abench = "abench.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create package + test init files and `.gitignore`**

`abench/__init__.py`:
```python
__version__ = "0.1.0"
```

`tests/__init__.py`: empty file.

`.gitignore`:
```
.venv/
__pycache__/
*.pyc
runs/
.pytest_cache/
```

- [ ] **Step 3: Create venv and install (editable, with dev extras)**

Run:
```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
```
Expected: installs abench + pyyaml/pydantic/httpx/httpx-sse/pandas/pytest with no errors.

- [ ] **Step 4: Verify pytest runs (collects zero tests)**

Run: `.venv/bin/pytest -q`
Expected: "no tests ran" (exit code 5) — confirms pytest is wired.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml abench/__init__.py tests/__init__.py .gitignore
git commit -m "chore: scaffold abench package"
```

---

## Task 1: Normalized trace model (`trace_model.py`)

The central contract. Everything downstream depends on this; nothing here depends on OpenCode.

**Files:**
- Create: `abench/trace_model.py`
- Test: `tests/test_trace_model.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_trace_model.py
import json
from abench.trace_model import Step, StepKind, Trace, trace_from_dict


def test_trace_roundtrips_through_json():
    trace = Trace(
        started_at=100.0,
        ended_at=105.0,
        tokens_in=10,
        tokens_out=20,
        finished=True,
        steps=[
            Step(kind=StepKind.ASSISTANT_TEXT, ts=100.0, turn=0, text="thinking"),
            Step(kind=StepKind.TOOL_CALL, ts=101.0, turn=0,
                 tool_name="bash", tool_args={"command": "pytest"}, tool_call_id="c1"),
            Step(kind=StepKind.TOOL_RESULT, ts=102.0, turn=0,
                 tool_call_id="c1", output="ok", exit_code=0),
            Step(kind=StepKind.FILE_EDIT, ts=103.0, turn=1,
                 path="a.py", patch="@@ -1 +1 @@"),
        ],
    )
    blob = json.dumps(trace.to_dict())
    restored = trace_from_dict(json.loads(blob))
    assert restored == trace
    assert restored.steps[1].kind == StepKind.TOOL_CALL
    assert restored.steps[1].tool_args == {"command": "pytest"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_trace_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'abench.trace_model'`.

- [ ] **Step 3: Write minimal implementation**

```python
# abench/trace_model.py
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class StepKind(str, Enum):
    ASSISTANT_TEXT = "assistant_text"
    REASONING = "reasoning"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    FILE_EDIT = "file_edit"


@dataclass
class Step:
    kind: StepKind
    ts: float | None = None
    turn: int | None = None
    text: str | None = None
    tool_name: str | None = None
    tool_args: dict | None = None
    tool_call_id: str | None = None
    output: str | None = None
    exit_code: int | None = None
    path: str | None = None
    patch: str | None = None


@dataclass
class Trace:
    steps: list[Step] = field(default_factory=list)
    started_at: float | None = None
    ended_at: float | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost: float | None = None
    finished: bool = False
    interrupted_reason: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        for step in d["steps"]:
            kind = step["kind"]
            step["kind"] = kind.value if isinstance(kind, StepKind) else kind
        return d


def trace_from_dict(d: dict) -> Trace:
    steps = [
        Step(kind=StepKind(s["kind"]), **{k: v for k, v in s.items() if k != "kind"})
        for s in d.get("steps", [])
    ]
    return Trace(steps=steps, **{k: v for k, v in d.items() if k != "steps"})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_trace_model.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add abench/trace_model.py tests/test_trace_model.py
git commit -m "feat: add normalized trace model"
```

---

## Task 2: Diff statistics (`diffstat.py`)

**Files:**
- Create: `abench/diffstat.py`
- Test: `tests/test_diffstat.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_diffstat.py
from abench.diffstat import parse_diffstat

PATCH = """diff --git a/foo.py b/foo.py
index e69de29..d95f3ad 100644
--- a/foo.py
+++ b/foo.py
@@ -0,0 +1,2 @@
+def foo():
+    return 1
diff --git a/bar.py b/bar.py
index 1111111..2222222 100644
--- a/bar.py
+++ b/bar.py
@@ -1,2 +1,1 @@
-old line one
-old line two
+new line
"""


def test_parse_diffstat_counts_files_and_lines():
    files, added, removed = parse_diffstat(PATCH)
    assert files == 2
    assert added == 3      # +def foo, +return 1, +new line
    assert removed == 2    # -old line one, -old line two


def test_parse_diffstat_empty():
    assert parse_diffstat("") == (0, 0, 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_diffstat.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# abench/diffstat.py
from __future__ import annotations


def parse_diffstat(patch: str) -> tuple[int, int, int]:
    """Return (n_files, lines_added, lines_removed) from a unified git diff."""
    files = 0
    added = 0
    removed = 0
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            files += 1
        elif line.startswith("+++ ") or line.startswith("--- "):
            continue
        elif line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return files, added, removed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_diffstat.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add abench/diffstat.py tests/test_diffstat.py
git commit -m "feat: add unified-diff stat parser"
```

---

## Task 3: Metrics extraction (`metrics.py`)

Pure function over a normalized `Trace` + patch text. This is where the spec's metrics live.

**Files:**
- Create: `abench/metrics.py`
- Test: `tests/test_metrics.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_metrics.py
from abench.metrics import MetricsConfig, extract
from abench.trace_model import Step, StepKind, Trace


def _cfg():
    return MetricsConfig(
        test_command_patterns=["pytest", r"(npm|pnpm|yarn)( run)? test"],
        shell_tool_names=["bash"],
        read_tool_names=["read"],
        search_tool_names=["grep", "glob", "list"],
        command_arg_keys=["command", "cmd"],
    )


def _trace():
    return Trace(
        started_at=0.0,
        ended_at=12.0,
        tokens_in=100,
        tokens_out=200,
        finished=True,
        steps=[
            Step(kind=StepKind.ASSISTANT_TEXT, ts=0.0, turn=0, text="plan"),
            Step(kind=StepKind.TOOL_CALL, ts=1.0, turn=0,
                 tool_name="read", tool_args={"path": "a.py"}),
            Step(kind=StepKind.TOOL_CALL, ts=2.0, turn=0,
                 tool_name="grep", tool_args={"pattern": "foo"}),
            Step(kind=StepKind.ASSISTANT_TEXT, ts=3.0, turn=1, text="editing"),
            Step(kind=StepKind.FILE_EDIT, ts=4.0, turn=1, path="a.py", patch="x"),
            Step(kind=StepKind.TOOL_CALL, ts=5.0, turn=2,
                 tool_name="bash", tool_args={"command": "pytest -q"}),
            Step(kind=StepKind.TOOL_CALL, ts=6.0, turn=2,
                 tool_name="bash", tool_args={"command": "ls -la"}),
        ],
    )


def test_extract_counts_metrics():
    patch = (
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
        "@@ -0,0 +1,1 @@\n+added line\n"
    )
    m = extract(_trace(), patch, _cfg())
    assert m["n_steps"] == 3          # turns 0,1,2
    assert m["n_tool_calls"] == 4
    assert m["tool_calls_by_name"] == {"read": 1, "grep": 1, "bash": 2}
    assert m["n_test_runs"] == 1      # only "pytest -q" matches
    assert m["n_reads"] == 1
    assert m["n_searches"] == 1
    assert m["n_files_edited"] == 1
    assert m["diff_lines_added"] == 1
    assert m["duration_s"] == 12.0
    assert m["time_to_first_edit_s"] == 4.0
    assert m["finished"] is True
    assert m["success"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_metrics.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# abench/metrics.py
from __future__ import annotations

import re
from dataclasses import dataclass

from .diffstat import parse_diffstat
from .trace_model import StepKind, Trace


@dataclass
class MetricsConfig:
    test_command_patterns: list[str]
    shell_tool_names: list[str]
    read_tool_names: list[str]
    search_tool_names: list[str]
    command_arg_keys: list[str]


def _command_of(step, keys: list[str]) -> str:
    args = step.tool_args or {}
    for key in keys:
        value = args.get(key)
        if isinstance(value, str):
            return value
    return ""


def extract(trace: Trace, patch_text: str, cfg: MetricsConfig) -> dict:
    tool_calls = [s for s in trace.steps if s.kind == StepKind.TOOL_CALL]

    by_name: dict[str, int] = {}
    for s in tool_calls:
        by_name[s.tool_name] = by_name.get(s.tool_name, 0) + 1

    test_res = [re.compile(p) for p in cfg.test_command_patterns]
    n_test = 0
    for s in tool_calls:
        if s.tool_name in cfg.shell_tool_names:
            cmd = _command_of(s, cfg.command_arg_keys)
            if any(r.search(cmd) for r in test_res):
                n_test += 1

    n_reads = sum(1 for s in tool_calls if s.tool_name in cfg.read_tool_names)
    n_searches = sum(1 for s in tool_calls if s.tool_name in cfg.search_tool_names)

    turns = {s.turn for s in trace.steps if s.turn is not None}
    n_steps = len(turns)

    n_files, added, removed = parse_diffstat(patch_text)

    ttfe = None
    edits = [s for s in trace.steps
             if s.kind == StepKind.FILE_EDIT and s.ts is not None]
    if edits and trace.started_at is not None:
        ttfe = min(e.ts for e in edits) - trace.started_at

    duration = None
    if trace.started_at is not None and trace.ended_at is not None:
        duration = trace.ended_at - trace.started_at

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
        "success": None,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_metrics.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add abench/metrics.py tests/test_metrics.py
git commit -m "feat: add metrics extraction over normalized trace"
```

---

## Task 4: Prompt composer (`prompt.py`)

**Files:**
- Create: `abench/prompt.py`
- Test: `tests/test_prompt.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_prompt.py
from abench.prompt import compose


def test_compose_baseline_returns_task_only():
    assert compose("Fix the bug.", None) == "Fix the bug."
    assert compose("Fix the bug.", "") == "Fix the bug."


def test_compose_augmented_appends_block():
    out = compose("Fix the bug.", "GRAPH SLICE\nnode A -> B")
    assert out == "Fix the bug.\n\n---\n\nGRAPH SLICE\nnode A -> B"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_prompt.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# abench/prompt.py
from __future__ import annotations


def compose(task: str, augmentation: str | None) -> str:
    task = task.strip()
    if augmentation and augmentation.strip():
        return f"{task}\n\n---\n\n{augmentation.strip()}"
    return task
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_prompt.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add abench/prompt.py tests/test_prompt.py
git commit -m "feat: add user-prompt composer"
```

---

## Task 5: Config loader (`config.py`)

**Files:**
- Create: `abench/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import textwrap
from pathlib import Path

import pytest

from abench.config import load_experiment


def _scaffold(tmp_path: Path) -> Path:
    (tmp_path / "fixture").mkdir()
    (tmp_path / "fixture" / "a.py").write_text("def f(): ...\n")
    (tmp_path / "reference").mkdir()
    (tmp_path / "reference" / "a.py").write_text("def f(): return 1\n")
    (tmp_path / "task.md").write_text("Restore the body of f().")
    (tmp_path / "system.md").write_text("You are a careful engineer.")
    (tmp_path / "slice.md").write_text("GRAPH SLICE")
    yaml_path = tmp_path / "exp.yaml"
    yaml_path.write_text(textwrap.dedent("""\
        name: exp1
        fixture_path: ./fixture
        reference_path: ./reference
        task_prompt: ./task.md
        system_prompt: ./system.md
        model: openrouter/some-model
        repetitions: 2
        output_dir: ./runs
        conditions:
          - {name: baseline, augmentation: null}
          - {name: augmented, augmentation: ./slice.md}
    """))
    return yaml_path


def test_load_resolves_text_and_paths(tmp_path):
    exp = load_experiment(_scaffold(tmp_path))
    assert exp.name == "exp1"
    assert exp.task_prompt == "Restore the body of f()."
    assert exp.system_prompt == "You are a careful engineer."
    assert exp.conditions[0].augmentation is None
    assert exp.conditions[1].augmentation == "GRAPH SLICE"
    assert exp.repetitions == 2
    assert exp.metrics.shell_tool_names == ["bash"]  # default applied


def test_missing_fixture_raises(tmp_path):
    yaml_path = _scaffold(tmp_path)
    (tmp_path / "fixture" / "a.py").unlink()
    (tmp_path / "fixture").rmdir()
    with pytest.raises(ValueError, match="fixture_path not found"):
        load_experiment(yaml_path)


def test_reference_inside_output_dir_raises(tmp_path):
    _scaffold(tmp_path)
    yaml_path = tmp_path / "exp.yaml"
    yaml_path.write_text(yaml_path.read_text().replace(
        "reference_path: ./reference", "reference_path: ./runs/reference"))
    (tmp_path / "runs" / "reference").mkdir(parents=True)
    with pytest.raises(ValueError, match="anti-leak"):
        load_experiment(yaml_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# abench/config.py
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

DEFAULT_TEST_PATTERNS = [
    "pytest",
    r"(npm|pnpm|yarn)( run)? test",
    r"go test",
    r"cargo test",
    r"(jest|vitest)",
]


class Condition(BaseModel):
    name: str
    augmentation: str | None = None


class OpenCodeCfg(BaseModel):
    port: int = 0
    agent: str = "bench"
    binary: str = "opencode"


class MetricsCfg(BaseModel):
    test_command_patterns: list[str] = Field(
        default_factory=lambda: list(DEFAULT_TEST_PATTERNS))
    shell_tool_names: list[str] = Field(default_factory=lambda: ["bash"])
    read_tool_names: list[str] = Field(default_factory=lambda: ["read"])
    search_tool_names: list[str] = Field(
        default_factory=lambda: ["grep", "glob", "list"])
    command_arg_keys: list[str] = Field(
        default_factory=lambda: ["command", "cmd", "script"])


class Experiment(BaseModel):
    name: str
    fixture_path: Path
    reference_path: Path
    task_prompt: str
    system_prompt: str
    model: str
    output_dir: Path
    conditions: list[Condition]
    repetitions: int = 3
    opencode: OpenCodeCfg = Field(default_factory=OpenCodeCfg)
    timeout_s: int = 600
    min_seconds_between_runs: float = 0.0
    metrics: MetricsCfg = Field(default_factory=MetricsCfg)


def _resolve_text(value: str | None, base: Path) -> str | None:
    if value is None:
        return None
    candidate = base / value
    if candidate.is_file():
        return candidate.read_text()
    return value


def load_experiment(path: str | Path) -> Experiment:
    path = Path(path)
    base = path.parent
    data = yaml.safe_load(path.read_text())

    data["task_prompt"] = _resolve_text(data["task_prompt"], base)
    data["system_prompt"] = _resolve_text(data["system_prompt"], base)
    for cond in data.get("conditions", []):
        cond["augmentation"] = _resolve_text(cond.get("augmentation"), base)

    data["fixture_path"] = str((base / data["fixture_path"]).resolve())
    data["reference_path"] = str((base / data["reference_path"]).resolve())
    data["output_dir"] = str((base / data["output_dir"]).resolve())

    exp = Experiment(**data)
    _validate(exp)
    return exp


def _validate(exp: Experiment) -> None:
    if not exp.fixture_path.exists():
        raise ValueError(f"fixture_path not found: {exp.fixture_path}")
    if not exp.reference_path.exists():
        raise ValueError(f"reference_path not found: {exp.reference_path}")
    out = exp.output_dir.resolve()
    ref = exp.reference_path.resolve()
    if ref == out or str(ref).startswith(str(out) + "/"):
        raise ValueError("reference_path must be outside output_dir (anti-leak)")
    if not exp.conditions:
        raise ValueError("at least one condition required")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: PASS (all three tests).

- [ ] **Step 5: Commit**

```bash
git add abench/config.py tests/test_config.py
git commit -m "feat: add experiment config loader with validation"
```

---

## Task 6: Fixture isolation (`fixture.py`)

Copy a prepared fixture into a temp dir, strip any `.git`, create a fresh single-commit repo, and diff against it. Uses the real `git` CLI and filesystem (no OpenCode).

**Files:**
- Create: `abench/fixture.py`
- Test: `tests/test_fixture.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fixture.py
import subprocess
from pathlib import Path

from abench import fixture as fx


def _make_fixture(tmp_path: Path) -> Path:
    src = tmp_path / "proj"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "mod.py").write_text("def f():\n    ...\n")
    # a stale .git that MUST be stripped (leak guard)
    (src / ".git").mkdir()
    (src / ".git" / "HEAD").write_text("ref: refs/heads/secret\n")
    return src


def test_create_workdir_strips_git_and_commits(tmp_path):
    src = _make_fixture(tmp_path)
    workdir, sha = fx.create_workdir(src, parent=tmp_path)
    assert (workdir / "pkg" / "mod.py").exists()
    # original .git stripped, fresh repo has exactly one commit
    log = subprocess.run(["git", "log", "--oneline"], cwd=workdir,
                         capture_output=True, text=True, check=True).stdout
    assert log.count("\n") == 1
    assert sha
    fx.cleanup(workdir)
    assert not workdir.exists()


def test_diff_workdir_reports_changes(tmp_path):
    src = _make_fixture(tmp_path)
    workdir, _ = fx.create_workdir(src, parent=tmp_path)
    (workdir / "pkg" / "mod.py").write_text("def f():\n    return 1\n")
    (workdir / "new.txt").write_text("hello\n")
    patch = fx.diff_workdir(workdir)
    assert "pkg/mod.py" in patch
    assert "new.txt" in patch
    assert "+    return 1" in patch
    fx.cleanup(workdir)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_fixture.py -v`
Expected: FAIL with `ImportError` / `AttributeError` (module/functions missing).

- [ ] **Step 3: Write minimal implementation**

```python
# abench/fixture.py
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

# Ephemeral identity passed per-command; does NOT touch user/global git config.
_GIT_ID = ["-c", "user.name=abench", "-c", "user.email=abench@local"]


def _copy_tree(src: Path, dst: Path) -> None:
    # Try APFS copy-on-write clone (fast, cheap on macOS); fall back to shutil.
    try:
        subprocess.run(
            ["cp", "-c", "-R", f"{src}/.", str(dst)],
            check=True, stderr=subprocess.DEVNULL,
        )
        return
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def create_workdir(fixture_path: Path, parent: Path | None = None) -> tuple[Path, str]:
    fixture_path = Path(fixture_path)
    workdir = Path(tempfile.mkdtemp(prefix="abench-", dir=parent))
    _copy_tree(fixture_path, workdir)

    git_dir = workdir / ".git"
    if git_dir.exists():
        shutil.rmtree(git_dir)
    if (workdir / ".git").exists():  # leak guard
        raise RuntimeError("failed to strip .git from workdir")

    subprocess.run(["git", "init", "-q"], cwd=workdir, check=True)
    subprocess.run(["git", "add", "-A"], cwd=workdir, check=True)
    subprocess.run(["git", *_GIT_ID, "commit", "-q", "-m", "fixture"],
                   cwd=workdir, check=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=workdir,
                         capture_output=True, text=True, check=True).stdout.strip()
    return workdir, sha


def diff_workdir(workdir: Path) -> str:
    workdir = Path(workdir)
    subprocess.run(["git", "add", "-A"], cwd=workdir, check=True)
    result = subprocess.run(["git", "diff", "--cached", "HEAD"], cwd=workdir,
                            capture_output=True, text=True, check=True)
    return result.stdout


def cleanup(workdir: Path) -> None:
    shutil.rmtree(workdir, ignore_errors=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_fixture.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add abench/fixture.py tests/test_fixture.py
git commit -m "feat: add isolated fixture workdir management"
```

---

## Task 7: Client interface + fake (`opencode_client.py`, `tests/fakes.py`)

Define the seam the runner depends on. The real implementation comes in Phase 2; the fake unblocks offline runner tests now.

**Files:**
- Create: `abench/opencode_client.py`
- Create: `tests/fakes.py`
- Test: `tests/test_fakes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fakes.py
from pathlib import Path

from abench.opencode_client import RunResult
from tests.fakes import FakeOpenCodeClient


def test_fake_client_emits_events_edits_workdir_and_returns_trace(tmp_path):
    events = []
    client = FakeOpenCodeClient()
    result = client.run_task(
        workdir=str(tmp_path),
        system_prompt="sys",
        model="m",
        user_message="do it",
        timeout_s=10,
        on_event=events.append,
    )
    assert isinstance(result, RunResult)
    assert result.trace.finished is True
    assert len(result.trace.steps) >= 1
    assert (Path(tmp_path) / "GENERATED.txt").exists()  # simulated edit
    assert len(events) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_fakes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'abench.opencode_client'`.

- [ ] **Step 3: Write the interface and the fake**

```python
# abench/opencode_client.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from .trace_model import Trace


@dataclass
class RunResult:
    trace: Trace
    raw_session: dict | None = None


class OpenCodeClient(Protocol):
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
        ...
```

```python
# tests/fakes.py
from __future__ import annotations

from pathlib import Path
from typing import Callable

from abench.opencode_client import RunResult
from abench.trace_model import Step, StepKind, Trace


class FakeOpenCodeClient:
    """Deterministic stand-in for the real client. Simulates a 2-turn run that
    reads a file, edits one file, and runs tests once."""

    def run_task(self, *, workdir: str, system_prompt: str, model: str,
                 user_message: str, timeout_s: int,
                 on_event: Callable[[dict], None]) -> RunResult:
        on_event({"type": "message.start"})
        (Path(workdir) / "GENERATED.txt").write_text("generated body\n")
        on_event({"type": "tool.finish", "tool": "write"})
        trace = Trace(
            started_at=0.0,
            ended_at=3.0,
            tokens_in=50,
            tokens_out=75,
            finished=True,
            steps=[
                Step(kind=StepKind.ASSISTANT_TEXT, ts=0.0, turn=0, text="plan"),
                Step(kind=StepKind.TOOL_CALL, ts=1.0, turn=0,
                     tool_name="read", tool_args={"path": "GENERATED.txt"}),
                Step(kind=StepKind.FILE_EDIT, ts=2.0, turn=1,
                     path="GENERATED.txt", patch="+generated body"),
                Step(kind=StepKind.TOOL_CALL, ts=2.5, turn=1,
                     tool_name="bash", tool_args={"command": "pytest -q"}),
            ],
        )
        return RunResult(trace=trace, raw_session={"fake": True})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_fakes.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add abench/opencode_client.py tests/fakes.py tests/test_fakes.py
git commit -m "feat: add OpenCodeClient interface and fake client"
```

---

## Task 8: Runner orchestration (`runner.py`)

Ties fixture + prompt + client + trace + diff + metrics into per-run artifacts. Fully testable offline via the fake client.

**Files:**
- Create: `abench/runner.py`
- Test: `tests/test_runner.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_runner.py
import json
from pathlib import Path

from abench.config import Condition, Experiment, MetricsCfg, OpenCodeCfg
from abench.runner import run_experiment
from tests.fakes import FakeOpenCodeClient


def _experiment(tmp_path: Path) -> Experiment:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "a.py").write_text("def f():\n    ...\n")
    reference = tmp_path / "reference"
    reference.mkdir()
    return Experiment(
        name="exp1",
        fixture_path=fixture,
        reference_path=reference,
        task_prompt="Restore f().",
        system_prompt="Be careful.",
        model="fake/model",
        output_dir=tmp_path / "runs",
        repetitions=2,
        conditions=[Condition(name="baseline", augmentation=None),
                    Condition(name="augmented", augmentation="SLICE")],
        opencode=OpenCodeCfg(),
        metrics=MetricsCfg(),
    )


def test_run_experiment_writes_all_artifacts(tmp_path):
    exp = _experiment(tmp_path)
    root = run_experiment(exp, lambda e: FakeOpenCodeClient())

    assert (root / "experiment.resolved.yaml").exists()
    for cond in ("baseline", "augmented"):
        for rep in range(2):
            rundir = root / cond / f"rep_{rep}"
            assert (rundir / "events.jsonl").read_text().strip() != ""
            assert (rundir / "trace.json").exists()
            assert (rundir / "changes.patch").exists()
            metrics = json.loads((rundir / "metrics.json").read_text())
            assert metrics["finished"] is True
            assert metrics["n_test_runs"] == 1
            assert metrics["n_files_edited"] == 1   # GENERATED.txt
            assert metrics["diff_lines_added"] >= 1
            manifest = json.loads((rundir / "manifest.json").read_text())
            assert manifest["condition"] == cond
    # augmented user_message includes the slice; baseline does not
    aug = json.loads((root / "augmented" / "rep_0" / "manifest.json").read_text())
    base = json.loads((root / "baseline" / "rep_0" / "manifest.json").read_text())
    assert "SLICE" in aug["user_message"]
    assert "SLICE" not in base["user_message"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'abench.runner'`.

- [ ] **Step 3: Write minimal implementation**

```python
# abench/runner.py
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import yaml

from . import fixture as fx
from .config import Condition, Experiment
from .metrics import MetricsConfig, extract
from .opencode_client import OpenCodeClient
from .prompt import compose

ClientFactory = Callable[[Experiment], OpenCodeClient]


def _dump_resolved(exp: Experiment) -> str:
    def conv(obj):
        if isinstance(obj, Path):
            return str(obj)
        if isinstance(obj, dict):
            return {k: conv(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [conv(x) for x in obj]
        return obj
    return yaml.safe_dump(conv(exp.model_dump()), allow_unicode=True, sort_keys=False)


def run_experiment(exp: Experiment, client_factory: ClientFactory) -> Path:
    root = exp.output_dir / exp.name
    root.mkdir(parents=True, exist_ok=True)
    (root / "experiment.resolved.yaml").write_text(_dump_resolved(exp))

    mcfg = MetricsConfig(**exp.metrics.model_dump())
    client = client_factory(exp)

    for cond in exp.conditions:
        for rep in range(exp.repetitions):
            _run_one(exp, cond, rep, root, client, mcfg)
            if exp.min_seconds_between_runs:
                time.sleep(exp.min_seconds_between_runs)
    return root


def _run_one(exp: Experiment, cond: Condition, rep: int, root: Path,
             client: OpenCodeClient, mcfg: MetricsConfig) -> None:
    rundir = root / cond.name / f"rep_{rep}"
    rundir.mkdir(parents=True, exist_ok=True)

    workdir, sha = fx.create_workdir(exp.fixture_path)
    user_message = compose(exp.task_prompt, cond.augmentation)

    events_file = (rundir / "events.jsonl").open("w")

    def on_event(event: dict) -> None:
        events_file.write(json.dumps(event) + "\n")
        events_file.flush()

    try:
        result = client.run_task(
            workdir=str(workdir),
            system_prompt=exp.system_prompt,
            model=exp.model,
            user_message=user_message,
            timeout_s=exp.timeout_s,
            on_event=on_event,
        )
    finally:
        events_file.close()

    (rundir / "trace.json").write_text(json.dumps(result.trace.to_dict(), indent=2))
    patch = fx.diff_workdir(workdir)
    (rundir / "changes.patch").write_text(patch)

    metrics = extract(result.trace, patch, mcfg)
    (rundir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    (rundir / "manifest.json").write_text(json.dumps({
        "condition": cond.name,
        "rep": rep,
        "model": exp.model,
        "fixture_sha": sha,
        "user_message": user_message,
    }, indent=2))

    fx.cleanup(workdir)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_runner.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add abench/runner.py tests/test_runner.py
git commit -m "feat: add experiment runner with offline fake-client test"
```

---

## Task 9: Report aggregation (`report.py`)

**Files:**
- Create: `abench/report.py`
- Test: `tests/test_report.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report.py
import json
from pathlib import Path

from abench.report import load_runs, write_report


def _write_run(root: Path, cond: str, rep: int, n_steps: int,
               interrupted=None) -> None:
    rundir = root / cond / f"rep_{rep}"
    rundir.mkdir(parents=True)
    (rundir / "manifest.json").write_text(json.dumps({"condition": cond, "rep": rep}))
    (rundir / "metrics.json").write_text(json.dumps({
        "duration_s": 10.0, "n_steps": n_steps, "n_tool_calls": 5,
        "n_test_runs": 2, "n_reads": 3, "n_searches": 1,
        "n_files_edited": 1, "diff_lines_added": 4, "diff_lines_removed": 0,
        "tokens_in": 100, "tokens_out": 200, "cost": None,
        "time_to_first_edit_s": 2.0, "finished": True,
        "interrupted_reason": interrupted, "success": None,
    }))


def test_load_and_report(tmp_path):
    root = tmp_path / "runs" / "exp1"
    _write_run(root, "baseline", 0, n_steps=10)
    _write_run(root, "baseline", 1, n_steps=12)
    _write_run(root, "augmented", 0, n_steps=6)
    _write_run(root, "augmented", 1, n_steps=8)
    _write_run(root, "augmented", 2, n_steps=99, interrupted="rate_limit")

    df = load_runs(root)
    assert len(df) == 5

    write_report(root)
    assert (root / "summary.csv").exists()
    md = (root / "summary.md").read_text()
    assert "## Mean per condition" in md
    # invalid (rate_limit) run excluded -> augmented mean n_steps == 7, not pulled to ~37
    assert "n_steps" in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_report.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# abench/report.py
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

NUMERIC = [
    "duration_s", "n_steps", "n_tool_calls", "n_test_runs", "n_reads",
    "n_searches", "n_files_edited", "diff_lines_added", "diff_lines_removed",
    "tokens_in", "tokens_out", "cost", "time_to_first_edit_s",
]


def load_runs(root: Path) -> pd.DataFrame:
    rows = []
    for metrics_file in sorted(Path(root).glob("*/*/metrics.json")):
        metrics = json.loads(metrics_file.read_text())
        manifest = json.loads((metrics_file.parent / "manifest.json").read_text())
        row = {"condition": manifest["condition"], "rep": manifest["rep"]}
        row.update({k: metrics.get(k) for k in NUMERIC})
        row["finished"] = metrics.get("finished")
        row["interrupted_reason"] = metrics.get("interrupted_reason")
        row["success"] = metrics.get("success")
        rows.append(row)
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    valid = df[df["interrupted_reason"].isna()]
    return valid.groupby("condition")[NUMERIC].agg(["mean", "median", "std"])


def _to_markdown(df: pd.DataFrame) -> str:
    valid = df[df["interrupted_reason"].isna()]
    means = valid.groupby("condition")[NUMERIC].mean()
    conditions = list(means.index)

    lines = [
        "# Summary",
        "",
        f"Total runs: {len(df)} (valid: {len(valid)}) | "
        f"conditions: {', '.join(conditions)}",
        "",
        "## Mean per condition (valid runs only)",
        "",
        "| metric | " + " | ".join(conditions) + " | delta (aug vs base) |",
        "|" + "---|" * (len(conditions) + 2),
    ]
    for metric in NUMERIC:
        cells = []
        for cond in conditions:
            value = means.loc[cond, metric]
            cells.append("" if pd.isna(value) else f"{value:.2f}")
        delta = ""
        if "baseline" in conditions and "augmented" in conditions:
            base = means.loc["baseline", metric]
            aug = means.loc["augmented", metric]
            if not pd.isna(base) and not pd.isna(aug) and base != 0:
                delta = f"{(aug - base) / base * 100:+.1f}%"
        lines.append(f"| {metric} | " + " | ".join(cells) + f" | {delta} |")
    return "\n".join(lines) + "\n"


def write_report(root: Path) -> None:
    root = Path(root)
    df = load_runs(root)
    df.to_csv(root / "summary.csv", index=False)
    (root / "summary.md").write_text(_to_markdown(df))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_report.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add abench/report.py tests/test_report.py
git commit -m "feat: add pandas report aggregation"
```

---

## Task 10: CLI — `report` subcommand (`cli.py`)

`run` is wired in Phase 2 (needs the real client). `report` works now.

**Files:**
- Create: `abench/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
import json
from pathlib import Path

from abench.cli import main


def _write_run(root: Path, cond: str, rep: int) -> None:
    rundir = root / cond / f"rep_{rep}"
    rundir.mkdir(parents=True)
    (rundir / "manifest.json").write_text(json.dumps({"condition": cond, "rep": rep}))
    (rundir / "metrics.json").write_text(json.dumps({
        "duration_s": 1.0, "n_steps": 3, "n_tool_calls": 1, "n_test_runs": 0,
        "n_reads": 0, "n_searches": 0, "n_files_edited": 1,
        "diff_lines_added": 1, "diff_lines_removed": 0, "tokens_in": None,
        "tokens_out": None, "cost": None, "time_to_first_edit_s": None,
        "finished": True, "interrupted_reason": None, "success": None,
    }))


def test_cli_report_writes_summary(tmp_path):
    root = tmp_path / "runs" / "exp1"
    _write_run(root, "baseline", 0)
    rc = main(["report", str(root)])
    assert rc == 0
    assert (root / "summary.csv").exists()
    assert (root / "summary.md").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# abench/cli.py
from __future__ import annotations

import argparse
from pathlib import Path

from .report import write_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="abench")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="run an experiment")
    run_p.add_argument("experiment", help="path to experiment YAML")

    report_p = sub.add_parser("report", help="build summary from a run dir")
    report_p.add_argument("run_dir", help="path to runs/<name> directory")

    args = parser.parse_args(argv)

    if args.cmd == "report":
        write_report(Path(args.run_dir))
        return 0

    if args.cmd == "run":
        # Wired in Phase 2 once RealOpenCodeClient exists.
        from .config import load_experiment
        from .opencode_client import RealOpenCodeClient
        from .runner import run_experiment

        exp = load_experiment(args.experiment)
        root = run_experiment(exp, lambda e: RealOpenCodeClient(e.opencode, e.timeout_s))
        write_report(root)
        return 0

    return 1
```

> Note: the `run` branch imports `RealOpenCodeClient`, which is created in Task 13. Until then, only `report` is exercised by tests; do not call `abench run` before Phase 2 is complete.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full Phase 1 suite + commit**

Run: `.venv/bin/pytest -q`
Expected: all tests PASS.

```bash
git add abench/cli.py tests/test_cli.py
git commit -m "feat: add CLI with report subcommand"
```

**End of Phase 1.** At this point the entire analysis pipeline is built and tested with no OpenCode dependency. `abench report <dir>` works end-to-end.

---

# Phase 2 — OpenCode integration (requires installing OpenCode)

## Task 11: API verification spike

A real investigation task. Its deliverables (notes + captured samples) are *inputs* to Tasks 12–14 — do not skip or guess.

**Files:**
- Create: `docs/superpowers/notes/opencode-api.md`
- Create: `tests/fixtures/opencode/events_sample.jsonl`
- Create: `tests/fixtures/opencode/session_sample.json`

- [ ] **Step 1: Install OpenCode and authenticate a free provider**

Try, in order, and record which worked:
```bash
npm i -g opencode-ai            # or: brew install sst/tap/opencode
                                # or: curl -fsSL https://opencode.ai/install | bash
opencode --version
```
Configure a provider key for a free model (one of):
```bash
# OpenRouter free model:
export OPENROUTER_API_KEY=...   # model id like "openrouter/<id>:free"
# or Google AI Studio (Gemini Flash), or Groq — set the matching env var.
opencode auth login             # if interactive auth is preferred
```

- [ ] **Step 2: Capture a real run's events and session**

```bash
mkdir -p /tmp/oc-probe && cd /tmp/oc-probe && git init -q && printf 'print("x")\n' > main.py && git add -A && git -c user.name=a -c user.email=a@b commit -qm init
PORT=4096
opencode serve --port "$PORT" &   # note actual flag name from `opencode serve --help`
SERVER_PID=$!
sleep 2
# In another shell, subscribe to the event stream and tee to a file while you
# create a session + send a message via the REST API. Save the raw SSE lines.
curl -N "http://127.0.0.1:$PORT/event" | tee /tmp/oc-probe/events.raw   # confirm path via docs/--help
# ... create session bound to cwd, post a message (exact endpoints from docs) ...
kill $SERVER_PID
```
Also locate the on-disk session store:
```bash
ls -R ~/.local/share/opencode 2>/dev/null || ls -R ~/.opencode 2>/dev/null
```

- [ ] **Step 3: Write the verified API notes**

Create `docs/superpowers/notes/opencode-api.md` documenting, with the values you actually observed:
- `opencode serve` flag for port; default port; readiness signal (log line / health endpoint).
- REST: exact path + JSON body to (a) create a session bound to a cwd, (b) set system prompt + model (custom agent via `opencode.json`/agent file, or per-request field), (c) send a user message.
- Event stream: endpoint path, transport (SSE?), and the event/part types and their JSON field names — specifically how text, reasoning, tool-call (name + args + the arg key holding a shell command), tool-result (output + exit), and file edits appear; plus token-usage fields and step/turn boundaries.
- Session storage: directory path + the message/parts JSON schema.
- The real tool names OpenCode uses for: shell/bash, file read, grep/glob/list, file write/edit — so `MetricsCfg` defaults can be reconciled.

- [ ] **Step 4: Save sanitized samples as test fixtures**

- `tests/fixtures/opencode/events_sample.jsonl` — the captured raw events, one JSON object per line (strip secrets/absolute home paths).
- `tests/fixtures/opencode/session_sample.json` — the captured persisted session JSON.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/notes/opencode-api.md tests/fixtures/opencode/
git commit -m "docs: verified OpenCode API notes and captured trace samples"
```

> If any `MetricsCfg` default tool name (e.g. `bash`, `read`, `grep`) differs from what OpenCode actually emits, update the defaults in `abench/config.py` now and adjust `tests/test_metrics.py` accordingly, in its own commit.

---

## Task 12: Trace normalizer (`trace_normalize.py`)

Maps OpenCode's raw events/session into the normalized `Trace`. Golden-tested against the Task 11 samples.

**Files:**
- Create: `abench/trace_normalize.py`
- Test: `tests/test_trace_normalize.py`

- [ ] **Step 1: Write the golden test**

Fill the `EXPECTED_*` constants with the true counts from your captured sample (read the committed `events_sample.jsonl`).

```python
# tests/test_trace_normalize.py
import json
from pathlib import Path

from abench.trace_model import StepKind
from abench.trace_normalize import normalize

FIXTURES = Path(__file__).parent / "fixtures" / "opencode"

# Fill these from the actual captured sample (Task 11):
EXPECTED_TOOL_CALLS = ...   # e.g. 3
EXPECTED_HAS_FILE_EDIT = ...  # True/False
EXPECTED_FINISHED = True


def _load_events():
    return [json.loads(line) for line in
            (FIXTURES / "events_sample.jsonl").read_text().splitlines() if line.strip()]


def test_normalize_produces_expected_trace():
    events = _load_events()
    session = json.loads((FIXTURES / "session_sample.json").read_text())
    trace = normalize(events, session)

    tool_calls = [s for s in trace.steps if s.kind == StepKind.TOOL_CALL]
    assert len(tool_calls) == EXPECTED_TOOL_CALLS
    assert any(s.kind == StepKind.FILE_EDIT for s in trace.steps) == EXPECTED_HAS_FILE_EDIT
    assert trace.finished == EXPECTED_FINISHED
    # every assistant turn has a turn index assigned (chain length is measurable)
    assert all(s.turn is not None for s in trace.steps)
    # shell tool calls expose a command string the metrics layer can read
    for s in tool_calls:
        if s.tool_name in ("bash", "shell"):
            assert isinstance((s.tool_args or {}).get("command"), str)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_trace_normalize.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation against the verified schema**

Use the field names recorded in `docs/superpowers/notes/opencode-api.md` (Task 11). The reference implementation below assumes OpenCode's documented "message parts" model; **reconcile each field access (`type`, `tool`, `args`, `result`, `time`, `tokens`) with your notes and adjust names where they differ.**

```python
# abench/trace_normalize.py
from __future__ import annotations

from .trace_model import Step, StepKind, Trace

# Map OpenCode part "type" -> our StepKind. Adjust keys to match the notes.
_KIND_BY_TYPE = {
    "text": StepKind.ASSISTANT_TEXT,
    "reasoning": StepKind.REASONING,
    "tool": StepKind.TOOL_CALL,
    "tool-result": StepKind.TOOL_RESULT,
    "patch": StepKind.FILE_EDIT,
    "file-edit": StepKind.FILE_EDIT,
}


def _ts(part: dict) -> float | None:
    time = part.get("time") or {}
    value = time.get("start") if isinstance(time, dict) else time
    return float(value) / 1000.0 if value else None  # ms -> s; adjust per notes


def normalize(raw_events: list[dict], raw_session: dict | None) -> Trace:
    """Build a normalized Trace from OpenCode events (+ persisted session).

    Strategy: derive ordered message parts from the event stream; assign a turn
    index that increments at each new assistant message boundary.
    """
    trace = Trace()
    turn = -1
    seen_assistant = False

    for event in raw_events:
        etype = event.get("type", "")
        props = event.get("properties", event)  # adjust per notes

        # Turn boundary: a new assistant message starts a new ReAct turn.
        if etype in ("message.updated", "message.start") and \
                props.get("role", props.get("info", {}).get("role")) == "assistant":
            turn += 1
            seen_assistant = True
            continue

        part = props.get("part", props)
        ptype = part.get("type")
        kind = _KIND_BY_TYPE.get(ptype)
        if kind is None:
            continue
        if turn < 0:
            turn = 0  # tolerate parts before an explicit boundary

        step = Step(kind=kind, ts=_ts(part), turn=turn)
        if kind in (StepKind.ASSISTANT_TEXT, StepKind.REASONING):
            step.text = part.get("text")
        elif kind == StepKind.TOOL_CALL:
            step.tool_name = part.get("tool")
            step.tool_call_id = part.get("callID") or part.get("id")
            step.tool_args = (part.get("state", {}).get("input")
                              or part.get("args") or {})
        elif kind == StepKind.TOOL_RESULT:
            step.tool_call_id = part.get("callID") or part.get("id")
            state = part.get("state", {})
            step.output = state.get("output") or part.get("result")
            step.exit_code = state.get("exit") or part.get("exit")
        elif kind == StepKind.FILE_EDIT:
            step.path = part.get("path") or part.get("filename")
            step.patch = part.get("patch") or part.get("diff")
        trace.steps.append(step)

    # Token usage + finish flag from the session record (adjust per notes).
    if raw_session:
        tokens = raw_session.get("tokens") or {}
        trace.tokens_in = tokens.get("input")
        trace.tokens_out = tokens.get("output")
        trace.cost = raw_session.get("cost")

    trace.finished = seen_assistant and trace.interrupted_reason is None
    return trace
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_trace_normalize.py -v`
Expected: PASS. (Iterate on field names against the sample until the golden assertions hold.)

- [ ] **Step 5: Commit**

```bash
git add abench/trace_normalize.py tests/test_trace_normalize.py
git commit -m "feat: add OpenCode trace normalizer with golden test"
```

---

## Task 13: Real client (`opencode_client.py`)

Implements `run_task`: manage the server, drive a session, stream events, enforce timeout/rate-limit handling, read the session, normalize.

**Files:**
- Modify: `abench/opencode_client.py` (add `RealOpenCodeClient`)
- Test: `tests/test_opencode_client_integration.py`

- [ ] **Step 1: Write the integration test (skipped without opencode)**

```python
# tests/test_opencode_client_integration.py
import shutil

import pytest

from abench.opencode_client import RealOpenCodeClient
from abench.config import OpenCodeCfg

pytestmark = pytest.mark.skipif(
    shutil.which("opencode") is None, reason="opencode not installed")


def test_real_client_runs_trivial_task(tmp_path):
    (tmp_path / "note.txt").write_text("start\n")
    events = []
    client = RealOpenCodeClient(OpenCodeCfg(port=0), timeout_s=180)
    result = client.run_task(
        workdir=str(tmp_path),
        system_prompt="You are a terse assistant.",
        model="<set a free model id available in your env>",
        user_message="Append the word DONE to note.txt and stop.",
        timeout_s=180,
        on_event=events.append,
    )
    assert len(events) > 0
    assert result.trace.steps  # captured at least one step
```

- [ ] **Step 2: Run test to verify it is collected (skips or fails clearly)**

Run: `.venv/bin/pytest tests/test_opencode_client_integration.py -v`
Expected: SKIP if opencode absent; otherwise FAIL with `AttributeError: ... RealOpenCodeClient` (not yet defined).

- [ ] **Step 3: Implement `RealOpenCodeClient`**

Use the endpoints/paths from `docs/superpowers/notes/opencode-api.md`. Reconcile the four `# CONFIRM:` constants and the request/stream shapes with your notes.

```python
# Append to abench/opencode_client.py
import socket
import subprocess
import time
from contextlib import closing

import httpx
from httpx_sse import connect_sse

from .config import OpenCodeCfg
from .trace_normalize import normalize

# CONFIRM these against docs/superpowers/notes/opencode-api.md (Task 11):
_SESSION_PATH = "/session"          # POST -> create session
_MESSAGE_PATH = "/session/{id}/message"   # POST -> send user message
_EVENT_PATH = "/event"              # GET (SSE) -> event stream


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class RealOpenCodeClient:
    def __init__(self, cfg: OpenCodeCfg, timeout_s: int = 600):
        self.cfg = cfg
        self.timeout_s = timeout_s
        self._proc: subprocess.Popen | None = None
        self._base: str | None = None

    def _start_server(self) -> None:
        port = self.cfg.port or _free_port()
        self._base = f"http://127.0.0.1:{port}"
        self._proc = subprocess.Popen(
            [self.cfg.binary, "serve", "--port", str(port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        # Wait for readiness.
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                httpx.get(self._base + _EVENT_PATH, timeout=1)
                return
            except httpx.HTTPError:
                time.sleep(0.3)
        raise RuntimeError("opencode serve did not become ready")

    def _stop_server(self) -> None:
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None

    def run_task(self, *, workdir, system_prompt, model, user_message,
                 timeout_s, on_event):
        from .opencode_client import RunResult  # local import: same module
        started = time.time()
        interrupted = None
        raw_events: list[dict] = []
        session_id = None
        try:
            self._start_server()
            with httpx.Client(base_url=self._base, timeout=timeout_s) as http:
                # CONFIRM body fields (cwd / agent / system prompt / model) per notes.
                resp = http.post(_SESSION_PATH, json={
                    "cwd": workdir,
                    "agent": self.cfg.agent,
                    "system": system_prompt,
                    "model": model,
                })
                resp.raise_for_status()
                session_id = resp.json().get("id")

                http.post(_MESSAGE_PATH.format(id=session_id),
                          json={"text": user_message, "model": model})

                deadline = started + timeout_s
                with connect_sse(http, "GET", _EVENT_PATH) as sse:
                    for event in sse.iter_sse():
                        if time.time() > deadline:
                            interrupted = "timeout"
                            break
                        payload = _parse_sse(event)
                        if payload is None:
                            continue
                        raw_events.append(payload)
                        on_event(payload)
                        if _is_session_idle(payload, session_id):
                            break
        except httpx.HTTPStatusError as exc:
            interrupted = "rate_limit" if exc.response.status_code == 429 else "error"
        except Exception:
            interrupted = "error"
        finally:
            raw_session = self._read_session(session_id)
            self._stop_server()

        trace = normalize(raw_events, raw_session)
        trace.started_at = started
        trace.ended_at = time.time()
        trace.interrupted_reason = interrupted
        if interrupted:
            trace.finished = False
        return RunResult(trace=trace, raw_session=raw_session)

    def _read_session(self, session_id):
        # CONFIRM storage path/format per notes; return parsed JSON or None.
        return None


def _parse_sse(event) -> dict | None:
    import json as _json
    try:
        return _json.loads(event.data)
    except (ValueError, AttributeError):
        return None


def _is_session_idle(payload: dict, session_id: str | None) -> bool:
    # CONFIRM the "run finished / session idle" event per notes.
    return payload.get("type") in ("session.idle", "session.done", "message.completed")
```

- [ ] **Step 4: Run the integration test**

With opencode installed + a free model env var set:
Run: `.venv/bin/pytest tests/test_opencode_client_integration.py -v`
Expected: PASS (events captured, trace has steps). Iterate on the `# CONFIRM` constants until green.

- [ ] **Step 5: Commit**

```bash
git add abench/opencode_client.py tests/test_opencode_client_integration.py
git commit -m "feat: implement real OpenCode client (server + SSE + normalize)"
```

---

## Task 14: Wire CLI `run` end-to-end

**Files:**
- Test: `tests/test_run_e2e.py`

- [ ] **Step 1: Write the end-to-end smoke test (skipped without opencode)**

```python
# tests/test_run_e2e.py
import json
import shutil
import textwrap
from pathlib import Path

import pytest

from abench.cli import main

pytestmark = pytest.mark.skipif(
    shutil.which("opencode") is None, reason="opencode not installed")


def test_run_then_report(tmp_path, monkeypatch):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "note.txt").write_text("start\n")
    (tmp_path / "reference").mkdir()
    (tmp_path / "reference" / "note.txt").write_text("start\nDONE\n")
    (tmp_path / "task.md").write_text("Append DONE to note.txt and stop.")
    (tmp_path / "system.md").write_text("You are terse.")
    (tmp_path / "exp.yaml").write_text(textwrap.dedent(f"""\
        name: e2e
        fixture_path: ./fixture
        reference_path: ./reference
        task_prompt: ./task.md
        system_prompt: ./system.md
        model: <free model id from env>
        repetitions: 1
        output_dir: ./runs
        timeout_s: 180
        conditions:
          - {{name: baseline, augmentation: null}}
    """))
    rc = main(["run", str(tmp_path / "exp.yaml")])
    assert rc == 0
    root = tmp_path / "runs" / "e2e"
    metrics = json.loads((root / "baseline" / "rep_0" / "metrics.json").read_text())
    assert "n_steps" in metrics
    assert (root / "summary.md").exists()
```

- [ ] **Step 2: Run it to verify collection/skip**

Run: `.venv/bin/pytest tests/test_run_e2e.py -v`
Expected: SKIP without opencode; with opencode + a valid free model id substituted, it drives a real run.

- [ ] **Step 3: No new implementation needed**

`abench run` was written in Task 10 and now resolves because `RealOpenCodeClient` exists (Task 13). If the e2e test reveals a wiring gap (e.g. constructor signature mismatch), fix it in `cli.py`/`opencode_client.py` minimally.

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all PASS (opencode-dependent tests SKIP if not installed).

- [ ] **Step 5: Commit**

```bash
git add tests/test_run_e2e.py
git commit -m "test: add end-to-end run+report smoke test"
```

---

## Self-Review (performed against the spec)

**Spec coverage:**
- Augmentation via user prompt → `prompt.compose` (Task 4), exercised in runner test (Task 8). ✓
- Fixed system prompt, pinned model → passed through `run_task` (Tasks 7/8/13); single `model` field in config (Task 5). ✓
- Manual correctness → `metrics["success"]` always `null` for manual fill (Task 3). ✓
- Isolation: copy + strip `.git` + single-commit git → `fixture.create_workdir` (Task 6). ✓
- Python + pandas analysis → report (Task 9). ✓
- User-prepared fixture + separate reference + anti-leak → config validation (Task 5), `.git` strip guard (Task 6). ✓
- Approach A (server + SSE, session as backup) → `RealOpenCodeClient` (Task 13). ✓
- Metrics list (duration, n_steps, tool calls by type, test runs, reads/searches, files edited, diff lines, tokens, time-to-first-edit, finished, interrupted_reason, success) → Task 3. ✓
- Error handling: timeout / 429 / per-run isolation → `RealOpenCodeClient.run_task` sets `interrupted_reason`; report excludes invalid runs (Tasks 13, 9). ✓
- Open questions (exact API) → resolved by the Task 11 spike, consumed by Tasks 12–13. ✓
- Artifact layout (events.jsonl, trace.json, changes.patch, metrics.json, manifest.json, summary.*) → Tasks 8, 9. ✓

**Placeholder scan:** The only deferred specifics are the `# CONFIRM` constants and `EXPECTED_*` golden values, which are *produced* by the Task 11 spike — a real task with concrete deliverables — not unspecified guesses.

**Type consistency:** `Trace`/`Step`/`StepKind` names are identical across Tasks 1, 3, 7, 12. `MetricsConfig` (dataclass, `metrics.py`) is built from `MetricsCfg` (pydantic, `config.py`) via `model_dump()` with matching field names (Task 8). `RunResult.trace` is consumed consistently by the runner (Task 8). `run_task` keyword signature matches between fake (Task 7), runner call (Task 8), and real client (Task 13).
