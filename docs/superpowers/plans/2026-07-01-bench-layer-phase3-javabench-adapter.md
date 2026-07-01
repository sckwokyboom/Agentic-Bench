# Universal Benchmark Layer — Phase 1, Plan 3: JavaBench Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `javabench` benchmark adapter — **per-class instances**, graded by JavaBench's **official class-wise Pass@1** (delegated to JavaBench's own `evaluate_single_class`) — plus isolation ground-rules in the benchmark system prompt. All pure-Python parts are unit-tested here with fixtures/mocks; the **live class-wise grade runs on the prepared host** (needs Java/Gradle + a JavaBench checkout).

**Architecture:** An instance = one skeleton class (JavaBench dataset record `task_id`="PAxx/Class.java"). `materialize` copies the `projects/PAxx` **skeleton** project (stubbed classes + tests) into the workdir; the agent implements the target class file. `grade` extracts the agent's class from the workdir, wraps it in a ```java fence as a one-record predictions JSONL, and **delegates to JavaBench's `evaluate_single_class`** (run `evaluation.py` via subprocess with `cwd=<JavaBench checkout>`), then maps the result to a `GradeResult`. Firewall: the skeleton (`todo_src`) is agent-visible; the gold canonical (`projects/PAxx-Solution`) is touched only inside `grade`.

**Tech Stack:** Python ≥3.12 (venv is 3.14), pydantic v2, pytest. Live grade: JavaBench (Gradle 8.2, JUnit5) on the prepared host.

**Spec:** `docs/superpowers/specs/2026-07-01-universal-benchmark-layer-design.md` (§4 adapter seam, §7 dual-grading, §12 JavaBench facts). Builds on Plans 1–2 (merged to `main`): `abench/bench/{base,registry,smoke,expand,run}.py` + `config` benchmark seam + `run_experiment` dispatch.

**Decision (user, 2026-07-01):** match JavaBench's OWN official metric (class-wise Pass@1) for comparability; a pure whole-project holistic run is NOT a JavaBench official metric and is out of scope. Accepted caveat: class-wise is lenient (isolates the agent's class against the gold-canonical rest).

**Branch:** create `feat/javabench-adapter` off `main` before Task 1.

**Test command:** `.venv/bin/python -m pytest <path> -v` from repo root `/Users/sckwoky/Projects/Agentic-Bench`.

**JavaBench grading API (verbatim, from the cloned repo `app/test_env.py` + `evaluation.py`):**
- `TestEnv(root, todo_src, src)` — copies `src` (canonical `projects/PAxx-Solution`) to `root`.
- `replace(target, content)` — merges skeleton header (from `todo_src`) + generated body (from `content`, from first `"public"`), writes to `root/src/main/java/<target>`. Returns `{"has_todo": bool, "can_replace": bool}`.
- `compile()` → runs `./gradlew compileJava` + `compileTestJava`, returns `list[CompilerError]` (empty = ok).
- `run_test(target|None)` → `./gradlew test [--tests <FQN>] --rerun-tasks`, returns `((n_pass, n_total), stdout)`.
- `evaluate_single_class(sample_file, output)` — reads JSONL of `{task_id, target, completion}`, per record: `TestEnv(root=/tmp/..., todo_src=projects/<pid>, src=projects/<pid>-Solution)`, `replace(target, extract_code(completion))`, `compile()`, if ok `run_test(None)`; writes a JSON list of `{task_id, compile_errors:int, test_result:[n_pass,n_total], has_todo, can_replace}`.
- `extract_code(code)` — returns the first ```java … ``` block (so `completion` MUST be fenced).
- **TestEnv uses RELATIVE paths (`projects/PAxx`), so `evaluation.py` must run with `cwd=<JavaBench checkout root>`.**

**Explicitly DEFERRED (do NOT build here):** whole-project holistic grade; test-wise / Pass@k>1; per-condition tool gating; real live grade validation (host); the SWE adapter (Plan 4); Docker/egress (Plan 5).

---

## File structure

| File | Responsibility |
|------|----------------|
| `abench/bench/base.py` (modify) | Add `EnvSpec.source_dir: str | None = None` — host dir to materialize the workdir from (agent-safe skeleton path). |
| `abench/bench/javabench.py` (create) | `JavaBenchAdapter` (`load`, `materialize`, `grade`) + `_build_prompt` + `_run_javabench_grader`; self-registers. |
| `abench/bench/__init__.py` (modify) | Import `javabench` so it self-registers. |
| `abench/bench/run.py` (modify) | Apply isolation ground-rules + nonce to the benchmark system prompt (reuse fixture-mode's builder). |
| `tests/test_bench_javabench.py` | load / materialize / grade (mocked) tests, with a tiny fake JavaBench checkout fixture. |
| `tests/test_bench_run_groundrules.py` | benchmark system prompt carries the grounding guard + nonce. |

---

## Task 1: Add `EnvSpec.source_dir`

**Files:** Modify `abench/bench/base.py`; Test `tests/test_bench_base.py` (append).

**Context:** `materialize` receives an `AgentView` (firewall) and must know WHERE to copy the skeleton from. Carry that host path on `EnvSpec` (which is part of `AgentView`). It points to the SKELETON (agent-safe), never the gold canonical.

- [ ] **Step 1: failing test.** Append to `tests/test_bench_base.py`:

```python
def test_envspec_source_dir_default_and_set():
    assert EnvSpec(image="i", build_system="none").source_dir is None
    assert EnvSpec(image="i", build_system="gradle", source_dir="/skel").source_dir == "/skel"
```

- [ ] **Step 2: run, expect FAIL.** `.venv/bin/python -m pytest tests/test_bench_base.py::test_envspec_source_dir_default_and_set -v` → `TypeError` (unexpected kwarg `source_dir`).

- [ ] **Step 3: implement.** In `abench/bench/base.py`, add a field to `EnvSpec` (after `workdir_mount`):

```python
    source_dir: str | None = None  # host dir to materialize the workdir from (a
    # skeleton project). Agent-safe: never points at the gold/canonical solution.
```

- [ ] **Step 4: run, expect PASS.** `.venv/bin/python -m pytest tests/test_bench_base.py -v` (all pass, +1).

- [ ] **Step 5: commit.**
```bash
git add abench/bench/base.py tests/test_bench_base.py
git commit -m "feat(bench): EnvSpec.source_dir for adapter workdir materialization"
```

---

## Task 2: `JavaBenchAdapter.load` + registration

**Files:** Create `abench/bench/javabench.py`; Modify `abench/bench/__init__.py`; Test `tests/test_bench_javabench.py`.

**Context:** `load` reads `<checkout>/datasets/<context>/data-<PROJECT>.jsonl` (records `{task_id, target, code, code_context}`) into per-class `Instance`s. `subset` keys: `project` (e.g. "PA19") and `context` (default "selective-context"). The prompt uses `code_context` (JavaBench's sanctioned context), NOT `code`. Firewall: `env.source_dir` = skeleton path (agent-safe); `oracle` = `{javabench_root, project_id, target}` (grade derives the canonical from it).

- [ ] **Step 1: failing test.** Create `tests/test_bench_javabench.py`:

```python
import json
from pathlib import Path

import abench.bench  # registers adapters
from abench.bench import registry


def _fake_checkout(tmp_path: Path) -> Path:
    root = tmp_path / "JavaBench"
    ds = root / "datasets" / "selective-context"
    ds.mkdir(parents=True)
    rec = {
        "task_id": "PA19/Cell.java",
        "target": "game/map/cells/Cell.java",
        "code": "```java\n// skeleton\n```",
        "code_context": "public class Coordinate { }",
    }
    (ds / "data-PA19.jsonl").write_text(json.dumps(rec) + "\n")
    (root / "projects" / "PA19" / "src" / "main" / "java" / "game" / "map" / "cells").mkdir(parents=True)
    (root / "projects" / "PA19-Solution").mkdir(parents=True)
    return root


def test_javabench_registered():
    assert "javabench" in registry.available()


def test_load_per_class_instances(tmp_path: Path):
    root = _fake_checkout(tmp_path)
    adapter = registry.get_adapter("javabench")
    insts = list(adapter.load(root, {"project": "PA19"}))
    assert len(insts) == 1
    inst = insts[0]
    assert inst.instance_id == "PA19/Cell.java"
    assert inst.repo == "javabench/PA19"
    assert inst.env.build_system == "gradle"
    assert inst.env.source_dir == str(root / "projects" / "PA19")
    # firewall: oracle carries grade-only data; agent_view has none of it
    assert inst.oracle["project_id"] == "PA19"
    assert inst.oracle["target"] == "game/map/cells/Cell.java"
    assert not hasattr(inst.agent_view(), "oracle")
    # prompt uses code_context (sanctioned), not the raw `code`
    assert "Coordinate" in inst.task.prompt_text
```

- [ ] **Step 2: run, expect FAIL.** `.venv/bin/python -m pytest tests/test_bench_javabench.py -v` → `ModuleNotFoundError`/`KeyError: 'javabench'`.

- [ ] **Step 3: implement.** Create `abench/bench/javabench.py`:

```python
"""JavaBench adapter (per-class, official class-wise Pass@1).

Instance = one skeleton class. materialize copies the PAxx skeleton project into
the workdir; the agent implements the target class. grade delegates to JavaBench's
own evaluate_single_class (replace the agent's class into the canonical solution,
compile, run all tests). Firewall: skeleton (projects/PAxx) is agent-visible;
canonical (projects/PAxx-Solution) is touched only inside grade().

The live grade needs a JavaBench checkout + Java/Gradle (prepared host); the pure
parts (load/materialize + grade wiring) are unit-tested with fixtures/mocks."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Iterable

from . import registry
from .base import Anchors, AgentView, EnvSpec, GradeResult, Instance, TaskSpec

_DEFAULT_PROJECTS = ["PA19", "PA20", "PA21", "PA22"]
_DEFAULT_CONTEXT = "selective-context"


def _build_prompt(rec: dict) -> str:
    ctx = rec.get("code_context") or "(none)"
    return (
        f"Implement the Java class at `src/main/java/{rec['target']}` in this project. "
        "The file is present with stubbed method bodies marked `// TODO`; complete the "
        "implementation so the project's tests pass. Do not modify any test files.\n\n"
        "Related class signatures (context):\n" + ctx
    )


class JavaBenchAdapter:
    id = "javabench"

    def load(self, dataset: Path | None, subset: dict[str, Any] | None) -> Iterable[Instance]:
        root = Path(dataset)
        subset = subset or {}
        context = subset.get("context", _DEFAULT_CONTEXT)
        projects = [subset["project"]] if subset.get("project") else list(_DEFAULT_PROJECTS)
        for project_id in projects:
            data_file = root / "datasets" / context / f"data-{project_id}.jsonl"
            if not data_file.is_file():
                continue
            for line in data_file.read_text().splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                yield Instance(
                    instance_id=rec["task_id"],
                    repo=f"javabench/{project_id}",
                    task=TaskSpec(prompt_text=_build_prompt(rec)),
                    anchors=Anchors(),
                    env=EnvSpec(
                        image="none",
                        build_system="gradle",
                        source_dir=str(root / "projects" / project_id),
                    ),
                    oracle={
                        "javabench_root": str(root),
                        "project_id": project_id,
                        "target": rec["target"],
                    },
                )

    def materialize(self, view: AgentView, workdir: Path) -> None:  # Task 3
        raise NotImplementedError

    def grade(self, inst: Instance, source_diff: str, workdir: Path) -> GradeResult:  # Task 4
        raise NotImplementedError


registry.register(JavaBenchAdapter())
```

Then append to `abench/bench/__init__.py`:
```python
from . import javabench  # noqa: F401  (registers the javabench adapter on import)
```

- [ ] **Step 4: run, expect PASS.** `.venv/bin/python -m pytest tests/test_bench_javabench.py -v` (the 2 tests here pass; `materialize`/`grade` are stubbed until Tasks 3–4).

- [ ] **Step 5: commit.**
```bash
git add abench/bench/javabench.py abench/bench/__init__.py tests/test_bench_javabench.py
git commit -m "feat(bench): JavaBench adapter load() + per-class instances"
```

---

## Task 3: `JavaBenchAdapter.materialize`

**Files:** Modify `abench/bench/javabench.py`; Test `tests/test_bench_javabench.py` (append).

**Context:** Copy the skeleton project (`view.env.source_dir`) into the (already-created) workdir, and strip any VCS metadata so the agent can't read history. The canonical solution is a SIBLING dir (`projects/PAxx-Solution`) and must NOT be copied.

- [ ] **Step 1: failing test.** Append to `tests/test_bench_javabench.py`:

```python
def test_materialize_copies_skeleton_only(tmp_path: Path):
    root = _fake_checkout(tmp_path)
    # add a marker file into the skeleton and into the canonical
    (root / "projects" / "PA19" / "build.gradle").write_text("// skel\n")
    (root / "projects" / "PA19-Solution" / "SECRET.java").write_text("gold\n")
    adapter = registry.get_adapter("javabench")
    inst = list(adapter.load(root, {"project": "PA19"}))[0]

    workdir = tmp_path / "wd"
    workdir.mkdir()
    adapter.materialize(inst.agent_view(), workdir)

    assert (workdir / "build.gradle").read_text() == "// skel\n"
    # canonical/gold must NOT be present anywhere in the workdir
    assert not (workdir / "SECRET.java").exists()
    assert not any(p.name == "SECRET.java" for p in workdir.rglob("*"))
    assert not (workdir / ".git").exists()
```

- [ ] **Step 2: run, expect FAIL.** `.venv/bin/python -m pytest tests/test_bench_javabench.py::test_materialize_copies_skeleton_only -v` → `NotImplementedError`.

- [ ] **Step 3: implement.** Replace `materialize`'s body in `abench/bench/javabench.py`:

```python
    def materialize(self, view: AgentView, workdir: Path) -> None:
        src = Path(view.env.source_dir)
        shutil.copytree(src, workdir, dirs_exist_ok=True)
        gitdir = Path(workdir) / ".git"
        if gitdir.exists():
            shutil.rmtree(gitdir)
```

- [ ] **Step 4: run, expect PASS.** `.venv/bin/python -m pytest tests/test_bench_javabench.py -v`.

- [ ] **Step 5: commit.**
```bash
git add abench/bench/javabench.py tests/test_bench_javabench.py
git commit -m "feat(bench): JavaBench materialize (skeleton-only copy)"
```

---

## Task 4: `JavaBenchAdapter.grade` — delegate to JavaBench's `evaluate_single_class`

**Files:** Modify `abench/bench/javabench.py`; Test `tests/test_bench_javabench.py` (append).

**Context:** grade reads the agent's implemented class from the workdir, wraps it in a ```java fence, writes a one-record predictions JSONL, and runs JavaBench's own grader with `cwd=<javabench_root>`. It maps the result to `GradeResult`. The subprocess/grader invocation is isolated in `_run_javabench_grader(...)` so the unit test can monkeypatch it (no Java needed here); the LIVE run happens on the prepared host.

**IMPLEMENTER: confirm the exact CLI** — read `evaluation.py` in the JavaBench checkout to find how `evaluate_single_class` is exposed (a `click` command). Fill `_run_javabench_grader` to invoke it via `subprocess.run([...], cwd=javabench_root, ...)` writing `preds_file` and reading `out_file`. If there is no CLI entry for single-class, add `sys.path.insert(0, javabench_root)` and call `from evaluation import evaluate_single_class; evaluate_single_class(preds_file, out_file)` inside a subprocess `python -c` with `cwd=javabench_root`. Either way it must run with `cwd=javabench_root` (TestEnv uses relative `projects/…` paths).

- [ ] **Step 1: failing test.** Append to `tests/test_bench_javabench.py`:

```python
import abench.bench.javabench as jb


def _prep_graded_instance(tmp_path):
    root = _fake_checkout(tmp_path)
    adapter = registry.get_adapter("javabench")
    inst = list(adapter.load(root, {"project": "PA19"}))[0]
    workdir = tmp_path / "wd"
    workdir.mkdir()
    # the agent's implemented class file must exist at src/main/java/<target>
    tgt = workdir / "src" / "main" / "java" / "game" / "map" / "cells" / "Cell.java"
    tgt.parent.mkdir(parents=True)
    tgt.write_text("public class Cell {}\n")
    return adapter, inst, workdir


def test_grade_resolved_when_all_tests_pass(tmp_path, monkeypatch):
    adapter, inst, workdir = _prep_graded_instance(tmp_path)
    monkeypatch.setattr(jb, "_run_javabench_grader", lambda root, preds, out: [
        {"task_id": "PA19/Cell.java", "compile_errors": 0,
         "test_result": [7, 7], "has_todo": False, "can_replace": True}])
    g = adapter.grade(inst, "diff", workdir)
    assert g.resolved is True
    assert g.standard_protocol is True
    assert g.abench["n_pass"] == 7 and g.abench["n_total"] == 7
    assert g.evaluator.startswith("javabench-class-wise")


def test_grade_not_resolved_on_partial_or_compile_error(tmp_path, monkeypatch):
    adapter, inst, workdir = _prep_graded_instance(tmp_path)
    monkeypatch.setattr(jb, "_run_javabench_grader", lambda root, preds, out: [
        {"task_id": "PA19/Cell.java", "compile_errors": 0,
         "test_result": [3, 7], "has_todo": False, "can_replace": True}])
    assert adapter.grade(inst, "diff", workdir).resolved is False

    monkeypatch.setattr(jb, "_run_javabench_grader", lambda root, preds, out: [
        {"task_id": "PA19/Cell.java", "compile_errors": 5,
         "test_result": [0, 0], "has_todo": False, "can_replace": True}])
    assert adapter.grade(inst, "diff", workdir).resolved is False
```

- [ ] **Step 2: run, expect FAIL.** `.venv/bin/python -m pytest tests/test_bench_javabench.py -k grade -v` → `NotImplementedError` / `AttributeError: _run_javabench_grader`.

- [ ] **Step 3: implement.** In `abench/bench/javabench.py` add imports `import subprocess, tempfile, os` and:

```python
_EVALUATOR_PIN = "javabench-class-wise@java-bench/JavaBench"


def _run_javabench_grader(javabench_root: str, preds_file: str, out_file: str) -> list[dict]:
    """Run JavaBench's evaluate_single_class with cwd=javabench_root and return the
    parsed result list. Isolated so tests can monkeypatch it (the real call needs
    Java/Gradle + a JavaBench checkout). IMPLEMENTER: confirm the exact CLI/entry
    from evaluation.py; it MUST run with cwd=javabench_root (relative projects/ paths)."""
    subprocess.run(
        ["python", "-c",
         "import sys; sys.path.insert(0, '.'); from evaluation import evaluate_single_class; "
         f"evaluate_single_class({preds_file!r}, {out_file!r})"],
        cwd=javabench_root, check=True,
    )
    return json.loads(Path(out_file).read_text())
```

and replace `grade`'s body:

```python
    def grade(self, inst: Instance, source_diff: str, workdir: Path) -> GradeResult:
        o = inst.oracle
        target = o["target"]
        agent_code = (Path(workdir) / "src" / "main" / "java" / target).read_text()
        completion = "```java\n" + agent_code + "\n```"
        tmp = Path(tempfile.mkdtemp(prefix="abench-jb-grade-"))
        try:
            preds = tmp / "preds.jsonl"
            out = tmp / "result.json"
            preds.write_text(json.dumps(
                {"task_id": inst.instance_id, "target": target, "completion": completion}) + "\n")
            results = _run_javabench_grader(o["javabench_root"], str(preds), str(out))
            r = results[0]
            n_pass, n_total = r.get("test_result") or [0, 0]
            resolved = (r.get("compile_errors", 1) == 0 and n_total > 0 and n_pass == n_total)
            return GradeResult(
                resolved=resolved,
                evaluator=_EVALUATOR_PIN,
                standard_protocol=True,
                official_report=r,
                abench={
                    "compile_errors": r.get("compile_errors"),
                    "n_pass": n_pass, "n_total": n_total,
                    "has_todo": r.get("has_todo"), "can_replace": r.get("can_replace"),
                },
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
```

- [ ] **Step 4: run, expect PASS.** `.venv/bin/python -m pytest tests/test_bench_javabench.py -v` (all pass; grade tests use the monkeypatched grader).

- [ ] **Step 5: commit.**
```bash
git add abench/bench/javabench.py tests/test_bench_javabench.py
git commit -m "feat(bench): JavaBench grade delegates to official evaluate_single_class (class-wise Pass@1)"
```

**HOST verification (not part of the unit suite — do on the prepared machine):** with a real JavaBench checkout and Java/Gradle installed, run one instance end-to-end (`abench run` on a `benchmark: {adapter: javabench, dataset: <checkout>, subset: {project: PA19}}` experiment against a real model) and confirm `grade.json`/`benchmark_summary.json` are produced and the verdict matches JavaBench's own `evaluate_single_class` output on a spot-check. Record the exact `evaluation.py` CLI used in `_run_javabench_grader` once confirmed.

---

## Task 5: Isolation ground-rules + nonce in the benchmark system prompt

**Files:** Modify `abench/bench/run.py`; Test `tests/test_bench_run_groundrules.py`.

**Context:** `run_benchmark` currently passes `exp.system_prompt` raw. Fixture mode wraps it with the grounding guard (`forbid_external_sources`) + a cache-busting nonce (`nonce_prefix`) — a validity control against memorization/lookup leakage (the opus review flagged this as needed before real runs). Reuse the SAME builder fixture mode uses.

**IMPLEMENTER:** read how `_run_one` builds the effective system prompt (in `abench/runner.py`, around lines 528–540) — it calls a helper (e.g. `build_system_prompt(...)` in `abench/prompt.py` or `abench/runner.py`) with the grounding guard + nonce derived from `exp.isolation.forbid_external_sources` / `exp.isolation.nonce_prefix`. Reuse that exact helper in `run_benchmark` to compute `system_prompt_eff`, and pass it to `client.run_task(system_prompt=system_prompt_eff, ...)`. Do NOT reimplement the guard text — call the shared helper so fixture and benchmark modes stay identical.

- [ ] **Step 1: failing test.** Create `tests/test_bench_run_groundrules.py`:

```python
from pathlib import Path

from abench.config import BenchmarkCfg, Condition, Experiment, MetricsCfg
from abench.metrics import MetricsConfig
from abench.bench.run import run_benchmark


class _RecordingClient:
    def __init__(self):
        self.system_prompts = []

    def run_task(self, **kwargs):
        self.system_prompts.append(kwargs["system_prompt"])
        Path(kwargs["workdir"], "calc.py").write_text("def add(a, b):\n    return a + b\n")
        from tests.fakes import FakeOpenCodeClient
        return FakeOpenCodeClient().run_task(**kwargs)


def _exp(tmp_path):
    return Experiment(
        name="smoke-bench", benchmark=BenchmarkCfg(adapter="smoke"),
        task_prompt="(unused)", system_prompt="BASE SYSTEM PROMPT",
        model="fake/model", output_dir=str(tmp_path / "runs"),
        repetitions=1, conditions=[Condition(name="baseline")],
    )


def test_benchmark_system_prompt_has_grounding_guard(tmp_path):
    exp = _exp(tmp_path)
    client = _RecordingClient()
    root = tmp_path / "root"; root.mkdir()
    run_benchmark(exp, client, MetricsConfig(**MetricsCfg().model_dump()), {}, root)
    sp = client.system_prompts[0]
    assert "BASE SYSTEM PROMPT" in sp
    # the grounding guard is present (forbid_external_sources defaults True).
    # IMPLEMENTER: assert against the actual guard marker used by the shared
    # builder — e.g. a distinctive phrase from GROUNDING_GUARD in abench/prompt.py.
    assert sp != "BASE SYSTEM PROMPT"  # it was wrapped, not passed raw
```

- [ ] **Step 2: run, expect FAIL.** `.venv/bin/python -m pytest tests/test_bench_run_groundrules.py -v` → currently `run_benchmark` passes the prompt raw, so `sp == "BASE SYSTEM PROMPT"` → assertion fails.

- [ ] **Step 3: implement.** In `abench/bench/run.py`, before the `client.run_task(...)` call, compute the effective system prompt via the shared builder (matching `_run_one`), then pass it. After confirming the real marker, tighten the test's final assertion to check for the actual grounding-guard phrase (replace the `!= "BASE SYSTEM PROMPT"` line).

- [ ] **Step 4: run, expect PASS.** `.venv/bin/python -m pytest tests/test_bench_run_groundrules.py tests/test_bench_run.py -v`.

- [ ] **Step 5: commit.**
```bash
git add abench/bench/run.py tests/test_bench_run_groundrules.py
git commit -m "feat(bench): apply isolation ground-rules + nonce to benchmark system prompt"
```

---

## Self-review

**Spec coverage:** per-class JavaBench instances (Task 2), skeleton materialization with firewall (Tasks 1, 3), official class-wise grade delegated to `evaluate_single_class` (Task 4), isolation ground-rules for real runs (Task 5). Dual-grading shape reused (`official_report` + `abench` on `GradeResult`). Holistic/test-wise/Pass@k>1 explicitly deferred.

**Placeholder scan:** the pure-Python parts (Tasks 1–3, and the grade mapping in Task 4) have complete code. Two integration points require the implementer to confirm an exact signature against real code they can read: the `evaluation.py` single-class CLI (Task 4) and the shared system-prompt builder (Task 5). Both are named + located + isolated behind a seam/helper with mock-based unit tests; they are not vague TODOs. The live JavaBench grade is explicitly a prepared-host step.

**Firewall (project premise):** `materialize` copies only `env.source_dir` (skeleton); the canonical `PAxx-Solution` is derived from `oracle` and touched only inside `grade`. Test `test_materialize_copies_skeleton_only` asserts no gold file reaches the workdir; `test_load_per_class_instances` asserts `agent_view()` has no `oracle`.

**Type/name consistency:** `EnvSpec.source_dir`, `JavaBenchAdapter.{load,materialize,grade}`, `oracle={javabench_root,project_id,target}`, `_run_javabench_grader(root, preds, out) -> list[dict]`, `GradeResult(resolved, evaluator, standard_protocol, official_report, abench)` — used identically across tasks and tests. Matches the Plan 1 `BenchmarkAdapter` protocol and Plan 2 `run_benchmark` grade→`verify_status` mapping.

**Risk:** only additive changes to shared files — `EnvSpec` gains an optional field (default None, no caller breaks), `run.py` swaps a raw prompt for the shared builder (fixture parity), `__init__.py` gains one import. `javabench.py` is new. No fixture-mode path touched.
