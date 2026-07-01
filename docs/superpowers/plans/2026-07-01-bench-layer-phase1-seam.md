# Universal Benchmark Layer — Phase 1, Plan 1: Adapter Seam Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pure, unit-tested `abench/bench/` adapter seam — the `BenchmarkAdapter` protocol, the `AgentView`/`OracleView` leakage firewall, the registry, an in-repo `smoke` adapter, the instance×condition×rep expansion, and the `benchmark:` config field — with no Docker, no live agent run, and no external benchmark.

**Architecture:** A benchmark is a source of `Instance`s. Each `Instance` splits into an `AgentView` (everything the agent/augmentation may see) and an `oracle` dict (gold/hidden data, reachable only by `grade()`). `agent_view()` structurally omits the oracle, so leakage is a type boundary, not a discipline. Adapters register by `id`; `Experiment` gains a `benchmark:` block as an alternative to `fixture_path`/`reference_path`. Live-run wiring into `runner.py` is deliberately **out of scope** here — it is Plan 2.

**Tech Stack:** Python ≥3.12, pydantic v2 (2.13.x), pytest 8. Dataclasses for internal domain objects; pydantic `BaseModel` for the YAML-loaded `BenchmarkCfg`.

**Spec:** `docs/superpowers/specs/2026-07-01-universal-benchmark-layer-design.md` (§4 the seam; §2 the firewall). This plan implements §4's protocol + firewall + config seam. Grading backends (§7), isolation (§5), and the real SWE/JavaBench adapters are later plans.

**Branch:** `feat/universal-bench-layer` (already checked out). All commits land here.

**Test command convention:** `.venv/bin/python -m pytest <path> -v` run from the repo root `/Users/sckwoky/Projects/Agentic-Bench`.

---

## File structure

| File | Responsibility |
|------|----------------|
| `abench/bench/__init__.py` | Package marker; imports `smoke` so the adapter self-registers on `import abench.bench`. |
| `abench/bench/base.py` | Domain dataclasses (`EnvSpec`, `TaskSpec`, `Anchors`, `AgentView`, `Instance`, `GradeResult`), the `BenchmarkAdapter` Protocol, and the `assert_no_oracle_leak` firewall guard. |
| `abench/bench/registry.py` | `register` / `get_adapter` / `available` — id → adapter lookup. |
| `abench/bench/smoke.py` | `SmokeAdapter` — a trivial 1-instance in-repo adapter for wiring tests; self-registers. |
| `abench/bench/expand.py` | `BenchRun` + `expand_plan(exp, instances)` — instance × condition × rep expansion. |
| `abench/config.py` (modify) | Add `BenchmarkCfg`; make `fixture_path`/`reference_path` optional; add `benchmark` field + `_check_task_source` validator; teach `load_experiment` / `_validate` about benchmark mode. |
| `tests/test_bench_base.py` | Firewall + dataclass tests. |
| `tests/test_bench_registry.py` | Registry tests. |
| `tests/test_bench_smoke.py` | Smoke adapter round-trip + registration. |
| `tests/test_config_benchmark.py` | `BenchmarkCfg` + validator + `load_experiment` benchmark YAML. |
| `tests/test_bench_expand.py` | Expansion counting. |

---

## Task 1: Domain dataclasses + leakage firewall (`base.py`)

**Files:**
- Create: `abench/bench/__init__.py`
- Create: `abench/bench/base.py`
- Test: `tests/test_bench_base.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_bench_base.py`:

```python
from abench.bench.base import (
    Instance, AgentView, TaskSpec, Anchors, EnvSpec, GradeResult,
    assert_no_oracle_leak,
)


def _make_instance() -> Instance:
    return Instance(
        instance_id="x-1",
        repo="r",
        task=TaskSpec(prompt_text="do it"),
        anchors=Anchors(existing_tests=("t",)),
        env=EnvSpec(image="img", build_system="maven"),
        oracle={"gold_patch": "SECRET FIX", "hidden_test_patch": "SECRET TEST"},
    )


def test_agent_view_excludes_oracle():
    view = _make_instance().agent_view()
    assert isinstance(view, AgentView)
    assert not hasattr(view, "oracle")
    # No oracle VALUE can appear in the agent view (structural, not disclaimed).
    assert "SECRET FIX" not in repr(view)
    assert "SECRET TEST" not in repr(view)
    assert_no_oracle_leak(view)


def test_instance_keeps_oracle_for_grading():
    inst = _make_instance()
    assert inst.oracle["gold_patch"] == "SECRET FIX"


def test_agent_view_carries_task_and_anchors():
    view = _make_instance().agent_view()
    assert view.task.prompt_text == "do it"
    assert view.anchors.existing_tests == ("t",)
    assert view.env.build_system == "maven"


def test_grade_result_carries_protocol_flag():
    g = GradeResult(resolved=True, evaluator="e@1", standard_protocol=True)
    assert g.resolved is True
    assert g.standard_protocol is True
    assert g.abench == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_bench_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'abench.bench'`.

- [ ] **Step 3: Write minimal implementation**

Create `abench/bench/__init__.py` (docstring-only for now — registration imports are wired in Task 3, once the modules exist):

```python
"""Universal benchmark layer: adapters that feed benchmark instances into the
existing abench run pipeline. The built-in adapters self-register when the
package is imported (wired in Task 3)."""
```

Create `abench/bench/base.py`:

```python
"""Core domain types for the benchmark layer + the AgentView/OracleView firewall.

A benchmark instance splits into two disjoint planes:
  - AgentView: everything the agent (and any augmentation) may legitimately see.
  - oracle (dict on Instance): gold patch / hidden tests / expected resolution —
    reachable ONLY via the full Instance, i.e. inside grade(). `agent_view()`
    never copies it, so leaking it would require deliberately changing signatures.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol, runtime_checkable

# Markers that must NEVER appear in an AgentView. Used by assert_no_oracle_leak
# as a defensive backstop on top of the structural guarantee.
_ORACLE_MARKERS: tuple[str, ...] = (
    "gold_patch",
    "hidden_test_patch",
    "expected_fail_to_pass",
    "expected_pass_to_pass",
    "reference_solution",
)


@dataclass(frozen=True)
class EnvSpec:
    """How to build/run the instance in isolation."""
    image: str
    build_system: str  # "maven" | "gradle" | "none"
    module_map: dict[str, str] = field(default_factory=dict)
    workdir_mount: str = "/work"


@dataclass(frozen=True)
class TaskSpec:
    """The legitimate agent-facing task input (issue text or codegen spec)."""
    prompt_text: str
    allowed_context: tuple[str, ...] = ()


@dataclass(frozen=True)
class Anchors:
    """Legitimately-known static seeds for augmentation. NEVER the hidden tests."""
    existing_tests: tuple[str, ...] = ()
    issue_entrypoints: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentView:
    """Everything the agent may see. No oracle fields exist on this type."""
    instance_id: str
    repo: str
    task: TaskSpec
    anchors: Anchors
    env: EnvSpec


@dataclass(frozen=True)
class GradeResult:
    """Dual-grading result: official verdict + abench's own statistics."""
    resolved: bool | None
    evaluator: str
    standard_protocol: bool
    official_report: dict[str, Any] = field(default_factory=dict)
    abench: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Instance:
    """Full benchmark record. `oracle` holds gold/hidden data and is reachable
    only here (and thus only inside grade())."""
    instance_id: str
    repo: str
    task: TaskSpec
    anchors: Anchors
    env: EnvSpec
    oracle: dict[str, Any] = field(default_factory=dict)

    def agent_view(self) -> AgentView:
        # Copies ONLY agent-safe fields. `self.oracle` is never referenced here,
        # so it cannot reach the agent plane.
        return AgentView(
            instance_id=self.instance_id,
            repo=self.repo,
            task=self.task,
            anchors=self.anchors,
            env=self.env,
        )


def assert_no_oracle_leak(view: AgentView) -> None:
    """Defensive backstop: raise if an AgentView somehow carries oracle data."""
    if hasattr(view, "oracle"):
        raise AssertionError("AgentView must not carry an `oracle` attribute")
    blob = repr(view)
    for marker in _ORACLE_MARKERS:
        if marker in blob:
            raise AssertionError(f"oracle marker {marker!r} leaked into AgentView")


@runtime_checkable
class BenchmarkAdapter(Protocol):
    """A benchmark plugged into the run pipeline. `id` is the registry key."""
    id: str

    def load(self, dataset: Path | None, subset: dict[str, Any] | None) -> Iterable[Instance]:
        ...

    def materialize(self, view: AgentView, workdir: Path) -> None:
        ...

    def grade(self, inst: Instance, source_diff: str, workdir: Path) -> GradeResult:
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_bench_base.py -v`
Expected: PASS (4 passed). (`__init__.py` is docstring-only at this point, so importing the package is side-effect-free.)

- [ ] **Step 5: Commit**

```bash
git add abench/bench/__init__.py abench/bench/base.py tests/test_bench_base.py
git commit -m "feat(bench): domain types + AgentView/OracleView firewall"
```

---

## Task 2: Adapter registry (`registry.py`)

**Files:**
- Create: `abench/bench/registry.py`
- Test: `tests/test_bench_registry.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_bench_registry.py`:

```python
import pytest

from abench.bench import registry
from abench.bench.base import GradeResult


class _Dummy:
    id = "dummy-x"

    def load(self, dataset, subset=None):
        return []

    def materialize(self, view, workdir):
        pass

    def grade(self, inst, source_diff, workdir):
        return GradeResult(resolved=None, evaluator="d", standard_protocol=True)


def test_register_and_get():
    d = _Dummy()
    registry.register(d)
    assert registry.get_adapter("dummy-x") is d
    assert "dummy-x" in registry.available()


def test_unknown_adapter_raises():
    with pytest.raises(KeyError):
        registry.get_adapter("nope-not-real")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_bench_registry.py -v`
Expected: FAIL — `ImportError: cannot import name 'registry'` (or `ModuleNotFoundError`).

- [ ] **Step 3: Write minimal implementation**

Create `abench/bench/registry.py`:

```python
"""Adapter registry: id -> BenchmarkAdapter."""
from __future__ import annotations

from .base import BenchmarkAdapter

_REGISTRY: dict[str, BenchmarkAdapter] = {}


def register(adapter: BenchmarkAdapter) -> None:
    _REGISTRY[adapter.id] = adapter


def get_adapter(adapter_id: str) -> BenchmarkAdapter:
    try:
        return _REGISTRY[adapter_id]
    except KeyError:
        raise KeyError(
            f"unknown benchmark adapter {adapter_id!r}; "
            f"registered: {sorted(_REGISTRY)}"
        )


def available() -> list[str]:
    return sorted(_REGISTRY)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_bench_registry.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add abench/bench/registry.py tests/test_bench_registry.py
git commit -m "feat(bench): adapter registry"
```

---

## Task 3: Smoke adapter (`smoke.py`)

**Files:**
- Create: `abench/bench/smoke.py`
- Modify: `abench/bench/__init__.py` (ensure the `smoke` import is active)
- Test: `tests/test_bench_smoke.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_bench_smoke.py`:

```python
from pathlib import Path

import abench.bench  # noqa: F401  (triggers smoke registration)
from abench.bench import registry


def test_smoke_registered():
    assert "smoke" in registry.available()


def test_smoke_roundtrip(tmp_path: Path):
    adapter = registry.get_adapter("smoke")
    inst = list(adapter.load(dataset=None, subset=None))[0]
    view = inst.agent_view()

    adapter.materialize(view, tmp_path)
    assert (tmp_path / "calc.py").exists()

    # Unsolved fixture: grade fails.
    g0 = adapter.grade(inst, source_diff="", workdir=tmp_path)
    assert g0.resolved is False

    # Apply the fix, grade passes.
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    g1 = adapter.grade(inst, source_diff="+ return a + b", workdir=tmp_path)
    assert g1.resolved is True
    assert g1.standard_protocol is True
    assert g1.abench["made_source_changes"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_bench_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'abench.bench.smoke'` (or `KeyError: 'smoke'`).

- [ ] **Step 3: Write minimal implementation**

Create `abench/bench/smoke.py`:

```python
"""A trivial in-repo adapter for wiring/integration tests. No Docker, no network,
no external dataset — one instance whose task is to implement add(a, b)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from . import registry
from .base import AgentView, Anchors, EnvSpec, GradeResult, Instance, TaskSpec


class SmokeAdapter:
    id = "smoke"

    def load(self, dataset: Path | None = None, subset: dict[str, Any] | None = None) -> Iterable[Instance]:
        yield Instance(
            instance_id="smoke-1",
            repo="smoke",
            task=TaskSpec(prompt_text="Make add(a, b) return a + b in calc.py"),
            anchors=Anchors(existing_tests=("test_add",)),
            env=EnvSpec(image="none", build_system="none"),
            oracle={
                "gold_patch": "def add(a, b): return a + b",
                "hidden_test_patch": "assert add(1, 2) == 3",
            },
        )

    def materialize(self, view: AgentView, workdir: Path) -> None:
        (workdir / "calc.py").write_text("def add(a, b):\n    raise NotImplementedError\n")
        (workdir / "task.md").write_text(view.task.prompt_text + "\n")

    def grade(self, inst: Instance, source_diff: str, workdir: Path) -> GradeResult:
        namespace: dict[str, Any] = {}
        resolved = False
        try:
            exec((workdir / "calc.py").read_text(), namespace)
            add = namespace.get("add")
            resolved = callable(add) and add(1, 2) == 3
        except Exception:
            resolved = False
        return GradeResult(
            resolved=bool(resolved),
            evaluator="smoke@1",
            standard_protocol=True,
            abench={"made_source_changes": bool(source_diff.strip())},
        )


registry.register(SmokeAdapter())
```

Update `abench/bench/__init__.py` to trigger registration on package import (append these two lines under the docstring):

```python
from . import registry  # noqa: F401
from . import smoke  # noqa: F401  (registers the smoke adapter on import)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_bench_smoke.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the whole bench suite so far**

Run: `.venv/bin/python -m pytest tests/test_bench_base.py tests/test_bench_registry.py tests/test_bench_smoke.py -v`
Expected: PASS (8 passed).

- [ ] **Step 6: Commit**

```bash
git add abench/bench/smoke.py abench/bench/__init__.py tests/test_bench_smoke.py
git commit -m "feat(bench): smoke adapter for wiring tests"
```

---

## Task 4: Config model — `BenchmarkCfg` + `Experiment` source validator

**Files:**
- Modify: `abench/config.py` (import line `8`; add `BenchmarkCfg` before `class Experiment` at `466`; change `fixture_path`/`reference_path` fields at `470-478`; add `benchmark` field; add `_check_task_source` validator at the end of `Experiment`)
- Test: `tests/test_config_benchmark.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_config_benchmark.py`:

```python
import pytest

from abench.config import BenchmarkCfg, Condition, Experiment


def test_benchmark_only_is_valid():
    exp = Experiment(
        name="t",
        benchmark=BenchmarkCfg(adapter="smoke"),
        task_prompt="p",
        system_prompt="s",
        model="m",
        output_dir="out",
        conditions=[Condition(name="baseline")],
    )
    assert exp.benchmark.adapter == "smoke"
    assert exp.fixture_path is None


def test_both_sources_rejected():
    with pytest.raises(Exception):
        Experiment(
            name="t",
            fixture_path="fx",
            reference_path="rf",
            benchmark=BenchmarkCfg(adapter="smoke"),
            task_prompt="p",
            system_prompt="s",
            model="m",
            output_dir="out",
            conditions=[Condition(name="baseline")],
        )


def test_neither_source_rejected():
    with pytest.raises(Exception):
        Experiment(
            name="t",
            task_prompt="p",
            system_prompt="s",
            model="m",
            output_dir="out",
            conditions=[Condition(name="baseline")],
        )


def test_fixture_requires_reference():
    with pytest.raises(Exception):
        Experiment(
            name="t",
            fixture_path="fx",
            task_prompt="p",
            system_prompt="s",
            model="m",
            output_dir="out",
            conditions=[Condition(name="baseline")],
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_config_benchmark.py -v`
Expected: FAIL — `ImportError: cannot import name 'BenchmarkCfg' from 'abench.config'`.

- [ ] **Step 3: Write minimal implementation**

Edit `abench/config.py`.

(a) Change the pydantic import at line `8` from:

```python
from pydantic import BaseModel, Field
```
to:
```python
from pydantic import BaseModel, Field, model_validator
```

(b) Insert `BenchmarkCfg` immediately before `class Experiment(BaseModel):` (line `466`):

```python
class BenchmarkCfg(BaseModel):
    """Run a standard benchmark (SWE-bench-java, JavaBench, …) instead of a local
    fixture. The adapter supplies per-instance working trees and grading."""
    adapter: str = Field(
        title="Adapter",
        description="Registered benchmark adapter id (e.g. 'swebench-java', 'javabench', 'smoke').",
    )
    dataset: Path | None = Field(
        default=None,
        title="Dataset",
        description="Path to the benchmark dataset, resolved relative to the experiment file.",
    )
    subset: dict[str, str] = Field(
        default_factory=dict,
        title="Subset",
        description="Filter passed to the adapter's load() (e.g. {repo: fasterxml/jackson-core}).",
    )
```

(c) Replace the `fixture_path` and `reference_path` fields (lines `470-478`) with optional versions, and add the `benchmark` field right after them:

```python
    fixture_path: Path | None = Field(
        default=None,
        title="Fixture path",
        description="Working tree the agent edits (the stripped project). Omit when `benchmark` is set.",
    )
    reference_path: Path | None = Field(
        default=None,
        title="Reference path",
        description="Ground-truth tree for comparison (the original project). Omit when `benchmark` is set.",
    )
    benchmark: BenchmarkCfg | None = Field(
        default=None,
        title="Benchmark",
        description="Run a standard benchmark instead of fixture_path/reference_path.",
    )
```

(d) Add this validator method at the very end of the `Experiment` class body (after the `target_methods` field, still indented as a class member):

```python
    @model_validator(mode="after")
    def _check_task_source(self) -> "Experiment":
        has_fixture = self.fixture_path is not None
        has_bench = self.benchmark is not None
        if has_fixture == has_bench:
            raise ValueError(
                "set EITHER fixture_path (+reference_path) OR benchmark — exactly one"
            )
        if has_fixture and self.reference_path is None:
            raise ValueError("fixture_path requires reference_path")
        return self
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_config_benchmark.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Guard against regressions in the existing config tests**

Run: `.venv/bin/python -m pytest tests/test_config.py tests/test_config_overlay.py -v`
Expected: PASS (existing behaviour unchanged — fixture-mode experiments still validate because they set `fixture_path` + `reference_path` and no `benchmark`).

- [ ] **Step 6: Commit**

```bash
git add abench/config.py tests/test_config_benchmark.py
git commit -m "feat(config): BenchmarkCfg + benchmark-xor-fixture validation"
```

---

## Task 5: Config loader — `load_experiment` + `_validate` benchmark mode

**Files:**
- Modify: `abench/config.py` (`load_experiment` lines `613-632`; `_validate` lines `635-659`)
- Test: `tests/test_config_benchmark.py` (add a case)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config_benchmark.py`:

```python
from pathlib import Path

from abench.config import load_experiment


def test_load_experiment_benchmark_yaml(tmp_path: Path):
    (tmp_path / "data.json").write_text("[]")
    (tmp_path / "exp.yaml").write_text(
        "name: t\n"
        "benchmark:\n"
        "  adapter: smoke\n"
        "  dataset: ./data.json\n"
        "task_prompt: solve it\n"
        "system_prompt: be good\n"
        "model: deepseek/deepseek-v4-flash\n"
        "output_dir: ./runs\n"
        "conditions:\n"
        "  - {name: baseline}\n"
    )
    exp = load_experiment(tmp_path / "exp.yaml")
    assert exp.benchmark.adapter == "smoke"
    assert exp.benchmark.dataset == (tmp_path / "data.json").resolve()
    assert exp.fixture_path is None


def test_load_experiment_unknown_adapter_rejected(tmp_path: Path):
    (tmp_path / "exp.yaml").write_text(
        "name: t\n"
        "benchmark:\n"
        "  adapter: does-not-exist\n"
        "task_prompt: p\n"
        "system_prompt: s\n"
        "model: m\n"
        "output_dir: ./runs\n"
        "conditions:\n"
        "  - {name: baseline}\n"
    )
    with pytest.raises(ValueError):
        load_experiment(tmp_path / "exp.yaml")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_config_benchmark.py::test_load_experiment_benchmark_yaml -v`
Expected: FAIL — `KeyError: 'fixture_path'` raised inside `load_experiment` (it unconditionally resolves `data["fixture_path"]`).

- [ ] **Step 3: Write minimal implementation**

Edit `load_experiment` (lines `626-628`). Replace:

```python
    data["fixture_path"] = str((base / data["fixture_path"]).resolve())
    data["reference_path"] = str((base / data["reference_path"]).resolve())
    data["output_dir"] = str((base / data["output_dir"]).resolve())
```
with:
```python
    if data.get("fixture_path") is not None:
        data["fixture_path"] = str((base / data["fixture_path"]).resolve())
    if data.get("reference_path") is not None:
        data["reference_path"] = str((base / data["reference_path"]).resolve())
    bench = data.get("benchmark")
    if bench and bench.get("dataset") is not None:
        bench["dataset"] = str((base / bench["dataset"]).resolve())
    data["output_dir"] = str((base / data["output_dir"]).resolve())
```

Edit `_validate` (lines `635-659`). Replace the whole function body with a benchmark-aware version:

```python
def _validate(exp: Experiment) -> None:
    if exp.benchmark is None:
        # Fixture mode (existing behaviour).
        if not exp.fixture_path.exists():
            raise ValueError(f"fixture_path not found: {exp.fixture_path}")
        if not exp.reference_path.exists():
            raise ValueError(f"reference_path not found: {exp.reference_path}")
        out = exp.output_dir.resolve()
        ref = exp.reference_path.resolve()
        if ref == out or str(ref).startswith(str(out) + "/"):
            raise ValueError("reference_path must be outside output_dir (anti-leak)")
        if exp.target_file is not None:
            full = exp.fixture_path / exp.target_file
            if not full.is_file():
                raise ValueError(
                    f"target_file not found relative to fixture_path: {exp.target_file}"
                )
    else:
        # Benchmark mode: the adapter must be registered; dataset (if given) exists.
        from .bench import registry as _bench_registry
        if exp.benchmark.adapter not in _bench_registry.available():
            raise ValueError(
                f"unknown benchmark adapter {exp.benchmark.adapter!r}; "
                f"registered: {_bench_registry.available()}"
            )
        if exp.benchmark.dataset is not None and not exp.benchmark.dataset.exists():
            raise ValueError(f"benchmark dataset not found: {exp.benchmark.dataset}")

    if not exp.conditions:
        raise ValueError("at least one condition required")
    names = [c.name for c in exp.conditions]
    if len(names) != len(set(names)):
        dupes = sorted({n for n in names if names.count(n) > 1})
        raise ValueError(f"duplicate condition name(s): {', '.join(dupes)}")
    for cond in exp.conditions:
        if cond.overlay is not None and not Path(cond.overlay).is_dir():
            raise ValueError(f"overlay dir not found: {cond.overlay} (condition {cond.name})")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_config_benchmark.py -v`
Expected: PASS (6 passed — the 4 from Task 4 plus the 2 new).

- [ ] **Step 5: Guard against regressions**

Run: `.venv/bin/python -m pytest tests/test_config.py tests/test_config_overlay.py -v`
Expected: PASS (fixture-mode validation unchanged).

- [ ] **Step 6: Commit**

```bash
git add abench/config.py tests/test_config_benchmark.py
git commit -m "feat(config): load_experiment + _validate handle benchmark mode"
```

---

## Task 6: Instance × condition × rep expansion (`expand.py`)

**Files:**
- Create: `abench/bench/expand.py`
- Test: `tests/test_bench_expand.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_bench_expand.py`:

```python
from abench.bench.base import Anchors, EnvSpec, Instance, TaskSpec
from abench.bench.expand import BenchRun, expand_plan
from abench.config import BenchmarkCfg, Condition, Experiment


def _exp(reps: int) -> Experiment:
    return Experiment(
        name="t",
        benchmark=BenchmarkCfg(adapter="smoke"),
        task_prompt="p",
        system_prompt="s",
        model="m",
        output_dir="out",
        repetitions=reps,
        conditions=[Condition(name="baseline"), Condition(name="alt")],
    )


def _inst(i: int) -> Instance:
    return Instance(
        instance_id=f"i{i}",
        repo="r",
        task=TaskSpec(prompt_text="x"),
        anchors=Anchors(),
        env=EnvSpec(image="none", build_system="none"),
    )


def test_expand_counts_instances_x_conditions_x_reps():
    exp = _exp(reps=3)
    runs = expand_plan(exp, [_inst(0), _inst(1)])
    assert len(runs) == 2 * 2 * 3
    assert isinstance(runs[0], BenchRun)
    assert {r.rep for r in runs} == {0, 1, 2}
    assert {r.condition.name for r in runs} == {"baseline", "alt"}
    assert {r.instance.instance_id for r in runs} == {"i0", "i1"}


def test_expand_empty_instances_is_empty():
    assert expand_plan(_exp(reps=2), []) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_bench_expand.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'abench.bench.expand'`.

- [ ] **Step 3: Write minimal implementation**

Create `abench/bench/expand.py`:

```python
"""Expand a benchmark experiment into the flat run plan: instance × condition × rep.

Mirrors the fixture-mode (condition × rep) plan, with the instance dimension added.
Runner wiring that consumes this is Plan 2."""
from __future__ import annotations

from dataclasses import dataclass

from ..config import Condition, Experiment
from .base import Instance


@dataclass(frozen=True)
class BenchRun:
    instance: Instance
    condition: Condition
    rep: int


def expand_plan(exp: Experiment, instances: list[Instance]) -> list[BenchRun]:
    runs: list[BenchRun] = []
    for inst in instances:
        for cond in exp.conditions:
            for rep in range(exp.repetitions):
                runs.append(BenchRun(instance=inst, condition=cond, rep=rep))
    return runs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_bench_expand.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the full new suite + a regression sweep**

Run: `.venv/bin/python -m pytest tests/test_bench_base.py tests/test_bench_registry.py tests/test_bench_smoke.py tests/test_bench_expand.py tests/test_config_benchmark.py tests/test_config.py -v`
Expected: PASS (all green).

- [ ] **Step 6: Commit**

```bash
git add abench/bench/expand.py tests/test_bench_expand.py
git commit -m "feat(bench): instance x condition x rep plan expansion"
```

---

## Self-review

**Spec coverage (this plan vs §4 + §2):**
- §4 `BenchmarkAdapter` protocol → Task 1 (`BenchmarkAdapter` Protocol).
- §4 `AgentView`/`OracleView` firewall → Task 1 (`agent_view()` + `assert_no_oracle_leak`; tests assert no value/attr leak).
- §4 dataclasses (`EnvSpec`/`TaskSpec`/`Anchors`/`GradeResult`/`Instance`) → Task 1.
- §4 registry → Task 2.
- §4 config seam (`benchmark:` block, fixture/reference optional) → Tasks 4–5.
- §4 "expand instances" → Task 6.
- Smoke adapter (wiring proof) → Task 3.
- **Deferred (later plans, explicitly out of scope here):** runner wiring + adapter.grade in the live loop (Plan 2), isolation/egress §5 (Plan 4), real SWE/JavaBench adapters + official graders §7 (Plans 2–3). No task claims these; no dangling references to them in code.

**Placeholder scan:** none — every step has full code or an exact command + expected result.

**Type consistency (checked across tasks):** `Instance(instance_id, repo, task, anchors, env, oracle)`, `AgentView` (same minus `oracle`), `agent_view()`, `TaskSpec.prompt_text`, `Anchors.existing_tests`, `EnvSpec.image/build_system`, `GradeResult(resolved, evaluator, standard_protocol, official_report, abench)`, `registry.register/get_adapter/available`, `BenchmarkCfg(adapter, dataset, subset)`, `Experiment.benchmark/fixture_path(optional)`, `expand_plan(exp, instances) -> list[BenchRun]`, `BenchRun(instance, condition, rep)` — names are used identically in every task and test.

**Note on `__init__.py` import ordering:** `__init__.py` starts docstring-only (Task 1) and only gains the `registry` + `smoke` imports in Task 3, once those modules exist. So importing `abench.bench` is side-effect-free in Tasks 1–2 and self-registers the smoke adapter from Task 3 onward. No comment/uncomment dance.
