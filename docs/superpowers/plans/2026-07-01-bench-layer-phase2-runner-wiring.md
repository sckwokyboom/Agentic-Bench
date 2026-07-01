# Universal Benchmark Layer — Phase 1, Plan 2: Runner Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire benchmark mode into the run pipeline: given an experiment with a `benchmark:` block, materialize each instance via its adapter, run the (baseline) agent, grade via `adapter.grade`, and write the same per-run artifacts (`events.jsonl`, `trace.json`, `changes.patch`, `metrics.json` + a new `grade.json`) — proven end-to-end with the `smoke` adapter and a fake client, with **zero changes to the working fixture-mode path**.

**Architecture:** A new compact `abench/bench/run.py::run_benchmark(...)` reuses the existing run primitives (`compose`, `client.run_task`, `fixture.diff_workdir`, `metrics.extract`, `Trace`) rather than surgically branching the 490-line `_run_one`. `run_experiment` gains a single dispatch branch (`if exp.benchmark is not None: run_benchmark(...); return root`) placed AFTER the common setup (client/mcfg/overlay_env/root) and BEFORE the fixture-specific baseline-verify + `_run_one` loop. The adapter's `GradeResult.resolved` is mapped onto `trace.verify_status` so the existing `success`/metrics plumbing works unchanged; the full dual-grade (official + abench) is also written to `grade.json` and into `metrics["benchmark"]`.

**Tech Stack:** Python ≥3.12, pydantic v2, pytest 8. Tests use the existing `tests/fakes.py::FakeOpenCodeClient` (no Java, Docker, model, or network).

**Spec:** `docs/superpowers/specs/2026-07-01-universal-benchmark-layer-design.md` (§4 the seam runner integration; §7 grading shape). Builds on Plan 1 (`docs/superpowers/plans/2026-07-01-bench-layer-phase1-seam.md`) which is merged to `main`: `abench/bench/{base,registry,smoke,expand}.py` + `config.BenchmarkCfg`.

**Branch:** create a fresh branch `feat/bench-runner-wiring` off `main` before Task 1.

**Test command convention:** `.venv/bin/python -m pytest <path> -v` from repo root `/Users/sckwoky/Projects/Agentic-Bench`.

**Explicitly DEFERRED to later plans (do NOT build here — no dangling references):** retry / rate-limit / idle-timeout parity with `_run_one`; isolation ground-rules (`forbid_external_sources`) + nonce in the benchmark system prompt (Plan 3, needed for real runs); per-condition tool gating (Phase 2 tipper); benchmark-aware `report.py`; the real JavaBench/SWE adapters + graders (Plans 3–4); Docker/egress (Plan 5).

---

## File structure

| File | Responsibility |
|------|----------------|
| `abench/fixture.py` (modify) | Factor a `_git_init_commit(workdir, message)` helper out of `create_workdir`; both fixture mode and benchmark mode use it. |
| `abench/bench/run.py` (create) | `run_benchmark(...)` — the benchmark run loop over instance × condition × rep; `_safe_instance_dirname`. |
| `abench/runner.py` (modify) | One dispatch branch in `run_experiment`: benchmark → `run_benchmark`. |
| `abench/cli.py` (modify) | Skip `write_report` for benchmark mode (its layout differs). |
| `tests/test_fixture_gitinit.py` | The git-init helper. |
| `tests/test_bench_run.py` | `run_benchmark` end-to-end with smoke + fake clients (solved / unsolved). |
| `tests/test_bench_run_dispatch.py` | `run_experiment` dispatches to benchmark mode. |

---

## Task 1: Factor `_git_init_commit` out of `create_workdir`

**Files:**
- Modify: `abench/fixture.py` (`create_workdir` at lines 68-94)
- Test: `tests/test_fixture_gitinit.py`

**Context:** `create_workdir` (fixture mode) does `git init / add -A / commit / rev-parse` inline. Benchmark mode needs the same "turn a materialized directory into a committed git workdir" step. Factor it into a reusable helper so both share it (DRY), without changing `create_workdir`'s behavior.

- [ ] **Step 1: Write the failing test**

Create `tests/test_fixture_gitinit.py`:

```python
import subprocess
from pathlib import Path

from abench.fixture import _git_init_commit


def test_git_init_commit_creates_repo_and_returns_sha(tmp_path: Path):
    (tmp_path / "a.txt").write_text("hello\n")
    sha = _git_init_commit(tmp_path)
    assert isinstance(sha, str) and len(sha) == 40
    assert (tmp_path / ".git").is_dir()
    # HEAD resolves to the returned sha
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert head == sha
    # the file is committed (clean tree)
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=tmp_path,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert status == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_fixture_gitinit.py -v`
Expected: FAIL — `ImportError: cannot import name '_git_init_commit'`.

- [ ] **Step 3: Write minimal implementation**

In `abench/fixture.py`, add the helper (place it just above `create_workdir`). Use the module's existing `_GIT_ID` constant (already used by `create_workdir`):

```python
def _git_init_commit(workdir: Path, message: str = "fixture") -> str:
    """Init a git repo in `workdir`, commit everything, return the HEAD sha.
    Shared by fixture mode (create_workdir) and benchmark mode (run_benchmark)."""
    subprocess.run(["git", "init", "-q"], cwd=workdir, check=True)
    subprocess.run(["git", "add", "-A"], cwd=workdir, check=True)
    subprocess.run(["git", *_GIT_ID, "commit", "-q", "-m", message],
                   cwd=workdir, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=workdir,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
```

Then replace the inline git block inside `create_workdir` (the four `subprocess.run` calls for init/add/commit/rev-parse, currently lines ~85-91) with:

```python
        sha = _git_init_commit(workdir)
        return workdir, sha
```

(Keep everything else in `create_workdir` — the `_copy_tree`, `.git` strip + leak guard, and `_apply_overlay` — exactly as is.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_fixture_gitinit.py -v`
Expected: PASS.

- [ ] **Step 5: Regression — the fixture-mode path still works**

Run: `.venv/bin/python -m pytest tests/test_run_e2e.py tests/test_runner.py -v`
Expected: PASS (create_workdir behavior unchanged). If a networkless/toolchain test is skipped, that is fine; no test should newly FAIL.

- [ ] **Step 6: Commit**

```bash
git add abench/fixture.py tests/test_fixture_gitinit.py
git commit -m "refactor(fixture): extract _git_init_commit shared by fixture + benchmark modes"
```

---

## Task 2: `run_benchmark` core (`abench/bench/run.py`)

**Files:**
- Create: `abench/bench/run.py`
- Test: `tests/test_bench_run.py`

**Context:** This is the benchmark run loop. It reuses: `registry.get_adapter`, `expand_plan` (Plan 1), `compose` (`abench/prompt.py`), `fixture._git_init_commit` + `fixture.diff_workdir`, `metrics.extract`, and the `OpenCodeClient` protocol (`client.run_task(...) -> RunResult(trace=Trace)`). It materializes each instance via the adapter, runs the agent, diffs, grades, maps `grade.resolved → trace.verify_status`, and writes per-run artifacts. Per-run layout: `root / <safe instance id> / <condition> / rep_<n>/`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_bench_run.py`:

```python
import json
from pathlib import Path

from abench.bench.run import run_benchmark, _safe_instance_dirname
from abench.config import BenchmarkCfg, Condition, Experiment, MetricsCfg
from abench.metrics import MetricsConfig
from tests.fakes import FakeOpenCodeClient


def _mcfg() -> MetricsConfig:
    # Build the runtime metrics config exactly as run_experiment does
    # (runner.py: `MetricsConfig(**exp.metrics.model_dump())`).
    return MetricsConfig(**MetricsCfg().model_dump())


def _bench_exp(tmp_path: Path) -> Experiment:
    return Experiment(
        name="smoke-bench",
        benchmark=BenchmarkCfg(adapter="smoke"),
        task_prompt="(unused in benchmark mode)",
        system_prompt="be good",
        model="fake/model",
        output_dir=str(tmp_path / "runs"),
        repetitions=1,
        conditions=[Condition(name="baseline")],
    )


class _SolvingClient:
    """Writes the smoke fix into the workdir, then delegates to the known-good
    fake for a valid Trace."""
    def run_task(self, **kwargs):
        Path(kwargs["workdir"], "calc.py").write_text("def add(a, b):\n    return a + b\n")
        return FakeOpenCodeClient().run_task(**kwargs)


def test_safe_instance_dirname():
    assert _safe_instance_dirname("apache__dubbo-10638") == "apache__dubbo-10638"
    assert _safe_instance_dirname("PA19/Cell.java") == "PA19_Cell.java"


def test_run_benchmark_solved(tmp_path: Path):
    exp = _bench_exp(tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    run_benchmark(exp, _SolvingClient(), _mcfg(), {}, root)

    rundir = root / "smoke-1" / "baseline" / "rep_0"
    assert (rundir / "events.jsonl").read_text().strip() != ""
    assert (rundir / "trace.json").exists()
    assert (rundir / "changes.patch").exists()

    grade = json.loads((rundir / "grade.json").read_text())
    assert grade["resolved"] is True
    assert grade["evaluator"] == "smoke@1"
    assert grade["standard_protocol"] is True

    metrics = json.loads((rundir / "metrics.json").read_text())
    assert metrics["success"] is True
    assert metrics["benchmark"]["instance_id"] == "smoke-1"
    assert metrics["benchmark"]["official"]["resolved"] is True


def test_run_benchmark_unsolved(tmp_path: Path):
    exp = _bench_exp(tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    # Plain fake never fixes calc.py, so the smoke grade fails.
    run_benchmark(exp, FakeOpenCodeClient(), _mcfg(), {}, root)

    rundir = root / "smoke-1" / "baseline" / "rep_0"
    grade = json.loads((rundir / "grade.json").read_text())
    assert grade["resolved"] is False
    metrics = json.loads((rundir / "metrics.json").read_text())
    assert metrics["success"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_bench_run.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'abench.bench.run'`.

- [ ] **Step 3: Write minimal implementation**

Create `abench/bench/run.py`:

```python
"""Benchmark run loop. Reuses the existing run primitives; materializes each
instance via its adapter and grades via adapter.grade (dual-grading). Kept
separate from the fixture-mode _run_one so the working fixture path is untouched.

DEFERRED (later plans): retry / rate-limit / idle-timeout parity, isolation
ground-rules + nonce in the system prompt, per-condition tool gating."""
from __future__ import annotations

import dataclasses
import json
import re
import tempfile
from pathlib import Path
from typing import Any, Callable

from ..fixture import _git_init_commit, diff_workdir
from ..metrics import extract
from ..prompt import compose
from . import registry
from .expand import expand_plan


def _safe_instance_dirname(instance_id: str) -> str:
    """Filesystem-safe directory name for an instance id (e.g. 'PA19/Cell.java')."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", instance_id)


def _verify_status_for(resolved: bool | None) -> str:
    if resolved is True:
        return "passed"
    if resolved is False:
        return "failed"
    return "skipped"


def run_benchmark(exp, client, mcfg, overlay_env: dict[str, str], root: Path,
                  *, emit: "Callable[[dict], None] | None" = None,
                  cancel_event: Any = None,
                  context_window: "int | None" = None) -> None:
    emit = emit or (lambda _p: None)
    adapter = registry.get_adapter(exp.benchmark.adapter)
    instances = list(adapter.load(exp.benchmark.dataset, exp.benchmark.subset or None))
    plan = expand_plan(exp, instances)

    for run in plan:
        if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
            break
        inst, cond, rep = run.instance, run.condition, run.rep
        rundir = root / _safe_instance_dirname(inst.instance_id) / cond.name / f"rep_{rep}"
        rundir.mkdir(parents=True, exist_ok=True)

        workdir = Path(tempfile.mkdtemp(prefix="abench-bench-"))
        adapter.materialize(inst.agent_view(), workdir)
        _git_init_commit(workdir, message="materialized")

        events_file = (rundir / "events.jsonl").open("w")

        def on_event(event: dict) -> None:
            events_file.write(json.dumps(event) + "\n")
            events_file.flush()

        user_message = compose(inst.task.prompt_text, cond.augmentation)
        try:
            result = client.run_task(
                workdir=str(workdir),
                system_prompt=exp.system_prompt,
                model=exp.model,
                user_message=user_message,
                timeout_s=exp.timeout_s,
                agent_tools=None,
                on_event=on_event,
                temperature=cond.temperature,
            )
        finally:
            events_file.close()

        patch = diff_workdir(workdir)
        (rundir / "changes.patch").write_text(patch)

        grade = adapter.grade(inst, patch, workdir)
        result.trace.verify_status = _verify_status_for(grade.resolved)

        (rundir / "trace.json").write_text(json.dumps(result.trace.to_dict(), indent=2))
        (rundir / "grade.json").write_text(json.dumps(dataclasses.asdict(grade), indent=2))

        metrics = extract(result.trace, patch, mcfg)
        metrics["benchmark"] = {
            "instance_id": inst.instance_id,
            "repo": inst.repo,
            "adapter": adapter.id,
            "standard_protocol": grade.standard_protocol,
            "official": {"resolved": grade.resolved, "evaluator": grade.evaluator},
            "abench": grade.abench,
        }
        (rundir / "metrics.json").write_text(json.dumps(metrics, indent=2))
        emit({"phase": "bench_run", "instance": inst.instance_id,
              "condition": cond.name, "rep": rep, "resolved": grade.resolved})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_bench_run.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add abench/bench/run.py tests/test_bench_run.py
git commit -m "feat(bench): run_benchmark loop (materialize -> agent -> grade -> artifacts)"
```

---

## Task 3: Dispatch from `run_experiment` + CLI report guard

**Files:**
- Modify: `abench/runner.py` (`run_experiment`, insert branch after `overlay_env = {...}` ~line 377, before `plan = ...` line 378)
- Modify: `abench/cli.py` (the `run` command, guard `write_report`)
- Test: `tests/test_bench_run_dispatch.py`

**Context:** `run_experiment` already builds `client`, `mcfg`, `overlay_env`, `root`, `emit` by line 377. Insert one branch so a benchmark experiment routes to `run_benchmark` and returns, skipping the fixture-specific baseline-verify + `_run_one` loop. The CLI calls `write_report(root)` after `run_experiment`; that reporter assumes the fixture layout (`root/cond/rep_N`), so skip it in benchmark mode.

- [ ] **Step 1: Write the failing test**

Create `tests/test_bench_run_dispatch.py`:

```python
import json
from pathlib import Path

from abench.config import BenchmarkCfg, Condition, Experiment
from abench.runner import run_experiment
from tests.fakes import FakeOpenCodeClient


class _SolvingClient:
    def run_task(self, **kwargs):
        Path(kwargs["workdir"], "calc.py").write_text("def add(a, b):\n    return a + b\n")
        return FakeOpenCodeClient().run_task(**kwargs)


def test_run_experiment_dispatches_to_benchmark(tmp_path: Path):
    exp = Experiment(
        name="smoke-bench",
        benchmark=BenchmarkCfg(adapter="smoke"),
        task_prompt="(unused)",
        system_prompt="be good",
        model="fake/model",
        output_dir=str(tmp_path / "runs"),
        repetitions=2,
        conditions=[Condition(name="baseline")],
    )
    root = run_experiment(exp, lambda e: _SolvingClient())

    # Benchmark layout: root/<instance>/<condition>/rep_N
    for rep in range(2):
        rundir = root / "smoke-1" / "baseline" / f"rep_{rep}"
        metrics = json.loads((rundir / "metrics.json").read_text())
        assert metrics["success"] is True
        assert metrics["benchmark"]["official"]["resolved"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_bench_run_dispatch.py -v`
Expected: FAIL — `run_experiment` takes the fixture path and raises (benchmark experiment has `fixture_path is None`; e.g. `AttributeError`/`TypeError` on `exp.fixture_path.parent` during baseline verify, or the `_run_one` fixture copy).

- [ ] **Step 3: Write minimal implementation**

In `abench/runner.py`, in `run_experiment`, immediately AFTER the line that sets `overlay_env` (`overlay_env = {k: expand_env_refs(v) for k, v in exp.overlay_env.items()}`, ~line 377) and BEFORE `plan = _plan if _plan is not None else compute_plan(exp)` (line 378), insert:

```python
    # Benchmark mode: instances + grading come from the adapter, not a local
    # fixture. Route to the benchmark loop, reusing the setup above (client,
    # mcfg, overlay_env, root), and skip the fixture-only baseline-verify + loop.
    if exp.benchmark is not None:
        from .bench.run import run_benchmark
        run_benchmark(exp, client, mcfg, overlay_env, root,
                      emit=emit, cancel_event=cancel_event,
                      context_window=context_window)
        _log(f"[abench] benchmark experiment={exp.name} finished → {root}")
        return root

```

In `abench/cli.py`, the `run` command currently does:
```python
        print(f"batch: {root.name}")
        write_report(root)
        return 0
```
Change it to skip the fixture-layout reporter in benchmark mode:
```python
        print(f"batch: {root.name}")
        if exp.benchmark is None:
            write_report(root)
        return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_bench_run_dispatch.py -v`
Expected: PASS.

- [ ] **Step 5: Regression — fixture-mode dispatch unchanged**

Run: `.venv/bin/python -m pytest tests/test_runner.py tests/test_cli_lib.py -v`
Expected: PASS (fixture experiments still take the original path; the new branch is skipped when `exp.benchmark is None`).

- [ ] **Step 6: Commit**

```bash
git add abench/runner.py abench/cli.py tests/test_bench_run_dispatch.py
git commit -m "feat(bench): route benchmark experiments through run_benchmark; guard CLI report"
```

---

## Task 4: Root-level benchmark summary (`benchmark_summary.json`)

**Files:**
- Modify: `abench/bench/run.py` (accumulate per-run results; write a summary at the end)
- Test: `tests/test_bench_run.py` (add a case)

**Context:** With no fixture-layout `write_report`, benchmark runs need a minimal top-level summary so results are inspectable: per-(instance, condition) resolved verdicts + an overall resolved-rate. This is the seed the (later) benchmark-aware report will build on.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bench_run.py`:

```python
def test_run_benchmark_writes_summary(tmp_path: Path):
    exp = _bench_exp(tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    run_benchmark(exp, _SolvingClient(), _mcfg(), {}, root)

    summary = json.loads((root / "benchmark_summary.json").read_text())
    assert summary["adapter"] == "smoke"
    assert summary["n_runs"] == 1
    assert summary["resolved_rate"] == 1.0
    assert summary["runs"][0]["instance_id"] == "smoke-1"
    assert summary["runs"][0]["condition"] == "baseline"
    assert summary["runs"][0]["resolved"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_bench_run.py::test_run_benchmark_writes_summary -v`
Expected: FAIL — `FileNotFoundError: benchmark_summary.json`.

- [ ] **Step 3: Write minimal implementation**

In `abench/bench/run.py`, accumulate a record per run and write the summary after the loop. Add a `summary: list[dict] = []` before the `for run in plan:` loop; inside the loop (after `metrics` is written) append:

```python
        summary.append({
            "instance_id": inst.instance_id,
            "condition": cond.name,
            "rep": rep,
            "resolved": grade.resolved,
        })
```

After the loop, add:

```python
    resolved_true = sum(1 for r in summary if r["resolved"] is True)
    scored = sum(1 for r in summary if r["resolved"] is not None)
    (root / "benchmark_summary.json").write_text(json.dumps({
        "experiment": exp.name,
        "adapter": adapter.id,
        "n_runs": len(summary),
        "resolved_rate": (resolved_true / scored) if scored else 0.0,
        "runs": summary,
    }, indent=2))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_bench_run.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Full new-suite sweep**

Run: `.venv/bin/python -m pytest tests/test_fixture_gitinit.py tests/test_bench_run.py tests/test_bench_run_dispatch.py tests/test_bench_base.py tests/test_bench_registry.py tests/test_bench_smoke.py tests/test_bench_expand.py tests/test_config_benchmark.py -v`
Expected: PASS (all green).

- [ ] **Step 6: Commit**

```bash
git add abench/bench/run.py tests/test_bench_run.py
git commit -m "feat(bench): write benchmark_summary.json (per-run verdicts + resolved-rate)"
```

---

## Self-review

**Spec coverage (this plan vs the roadmap's "runner wiring"):**
- Benchmark instances flow through the run pipeline → Tasks 2–3 (`run_benchmark` + `run_experiment` dispatch).
- Materialize via adapter (no fixture) → Task 2 (`adapter.materialize` + `_git_init_commit`).
- Dual-grading verdict via `adapter.grade`, mapped to `success` + written to `grade.json`/`metrics["benchmark"]` → Tasks 2–3.
- Same trace/metrics machinery reused (`extract`, `Trace.to_dict`) → Task 2.
- Zero fixture-mode regression → dispatch branch only triggers when `exp.benchmark is not None`; regression runs in Tasks 1, 3.
- Inspectable results without the fixture reporter → Task 4 summary.
- **Deferred (named, no dangling refs):** retry/idle parity, system-prompt isolation ground-rules + nonce, tool gating, benchmark report, real adapters/graders, Docker/egress.

**Placeholder scan:** none — every step has full code or an exact command + expected result.

**Type/name consistency:** `run_benchmark(exp, client, mcfg, overlay_env, root, *, emit, cancel_event, context_window)` — same call site in Task 2 (test), Task 3 (runner). `_safe_instance_dirname`, `_git_init_commit(workdir, message)`, `adapter.materialize(view, workdir)`, `adapter.grade(inst, source_diff, workdir) -> GradeResult(resolved, evaluator, standard_protocol, official_report, abench)`, `metrics["benchmark"]` keys, and the run layout `root/<safe id>/<condition>/rep_<n>/` are used identically across tasks. `client.run_task(**kwargs)` keyword set matches the `OpenCodeClient` Protocol and `FakeOpenCodeClient`.

**Import/cycle note:** `run_experiment` imports `run_benchmark` locally (function scope), matching the repo's pattern for `.bench` imports and avoiding any config↔bench / runner↔bench module-load cycle. `abench/bench/run.py` imports `..fixture`, `..metrics`, `..prompt`, `.registry`, `.expand` — none import `bench.run`, so no cycle.

**Risk note:** the only edits to existing files are (a) a pure refactor of `create_workdir`'s git block into a helper it still calls (Task 1, regression-tested), (b) one early-return branch in `run_experiment` guarded by `exp.benchmark is not None` (Task 3), and (c) a one-line `if` around the CLI reporter (Task 3). The fixture-mode path is otherwise untouched.
