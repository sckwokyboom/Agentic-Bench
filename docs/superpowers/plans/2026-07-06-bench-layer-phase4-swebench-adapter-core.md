# Universal Benchmark Layer — Phase 1, Plan 4: SWE-bench-java Adapter (pure-Python core) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `swebench-java` benchmark adapter's **pure-Python core** — `load` (91-instance dataset → per-instance `Instance`s behind the AgentView/oracle firewall), issue-only prompt, per-instance `EnvSpec`, the **source/test diff split** (§7), and a **DUAL-grading `grade`** that runs BOTH graders via mocked seams: (1) the official multi-swe-bench evaluator → the leaderboard-comparable verdict, and (2) abench's OWN methodology (scoped regression + repro quality, the same kind abench runs on the putValue experiment) → the richer picture the official criterion omits. Both verdicts land on `GradeResult` (`official_report` + `abench`). All parts are unit-tested here with fixtures/mocks (zero Docker/setup). The **live Docker materialize + real official-evaluator run are DEFERRED to the next plan** (they need Docker + the official image + a pinned multi-swe-bench checkout, and the exact evaluator CLI/predictions format is spec §10's open question — it will be read from the real repo, not guessed).

**Architecture:** An instance = one SWE-bench-java record (`instance_id`, e.g. `fasterxml__jackson-core-1234`). `load` reads `swe-bench-java-verified.json` (91 records) and yields one `Instance` per record: `problem_statement` → agent-visible task; gold `patch` + hidden `test_patch` + `FAIL_TO_PASS`/`PASS_TO_PASS` → `oracle` (grade-only). `grade` splits the agent's diff into source (graded) vs test (abench-only, never graded), delegates the source-diff to JavaBench-style seam `_run_swebench_evaluator` (mocked here), and maps the result to `GradeResult`. Firewall: the agent never sees `patch`/`test_patch`/`FAIL_TO_PASS`; `agent_view()` structurally excludes `oracle`.

**Tech Stack:** Python ≥3.12 (venv 3.14), pydantic v2, pytest. Live grade (next plan): Docker + official multi-swe-bench image + pinned evaluator.

**Spec:** `docs/superpowers/specs/2026-07-01-universal-benchmark-layer-design.md` (§2 invariants, §4 adapter seam + firewall, §7 dual-grading + diff-split, §10 open questions). Builds on Plans 1–3 (merged to `main`): `abench/bench/{base,registry,run,javabench,…}` + the `BenchmarkCfg` config seam (`adapter`/`dataset`/`subset`, already documents the `swebench-java` id + `{repo: fasterxml/jackson-core}` subset example) + `run_experiment` dispatch. Mirrors the proven `javabench.py` adapter shape (Plan 3).

**Dataset facts (verified, from memory `swebench-java-integration`):** HF `Daoguang/Multi-SWE-bench` → `swe-bench-java-verified.json`, 91 instances, clean SWE-bench schema. Per record: `repo`, `instance_id`, `base_commit`, `patch` (gold, multi-file), `test_patch` (hidden eval tests), `problem_statement` (issue), `hints_text` (PR discussion — NOT shown, may spoil), `FAIL_TO_PASS` (1–3 module-prefixed test CLASSES `module:pkg.ClassFQN`, e.g. `src:com.fasterxml…Test`), `PASS_TO_PASS` (**empty for all 91** → official criterion has no regression guard), `version` (e.g. "0.1"). **GOTCHA: `FAIL_TO_PASS`/`PASS_TO_PASS` are JSON-encoded STRINGS, not lists — `json.loads()` each before use, else you iterate characters.** 6 repos, 79% Jackson; 5 Maven + 1 Gradle (jib). Pilot = `fasterxml/jackson-core` (23 inst, 1 official image, Maven).

**Hard invariants honored (spec §2):** (1) no gold leakage — `patch` only in `oracle`, only `grade()` sees it; (2) no test leakage — `test_patch`/`FAIL_TO_PASS` only in `oracle`, the source/test **diff-split** guarantees the agent's own test edits are stripped before grading and the hidden tests are never on the agent's disk; (3) fidelity — agent input = `problem_statement` only (`hints_text` OFF); (4) honesty — `GradeResult.standard_protocol` + evaluator pin.

**Explicitly DEFERRED (do NOT build here) — only the LIVE, Docker/graph-gated bodies; their seams + `GradeResult` shape ARE built here:** live Docker materialize (repo lives inside the official image — spec §5); the real `_run_swebench_evaluator` body + predictions-file format (read from the pinned multi-swe-bench repo in the next plan — spec §10); the real `_run_abench_verify` body — abench's own methodology = blast-radius scoped-regression (Joern/graph reuse) + repro re-run (§7); class-level Maven/Gradle test selection; egress-lock (spec §5, a separate plan); the tipper (§6, Phase 2). `materialize` stays a `raise NotImplementedError` stub in this plan. NOTE: this is NOT dropping abench's methodology — its seam is first-class here (Task 3) and its agent-run-metrics half already runs via `run_benchmark` (Plan 2); only its build-environment-dependent verdict is Docker-gated, exactly like the official one.

**Branch:** create `feat/swebench-adapter-core` off `main` before Task 1.

**Test command:** `.venv/bin/python -m pytest <path> -v` from repo root `/Users/sckwoky/Projects/Agentic-Bench`.

---

## File structure

| File | Responsibility |
|------|----------------|
| `abench/bench/swebench_java.py` (create) | `SweBenchAdapter` (`load`, `materialize`-stub, dual-grading `grade`) + `_build_prompt` + `_as_list` (F2P/P2P decode) + `_image_ref` (image convention, isolated) + module-level `split_source_test_diff` + two mocked grade seams `_run_swebench_evaluator` (official) & `_run_abench_verify` (abench methodology); self-registers. |
| `abench/bench/__init__.py` (modify) | Import `swebench_java` so it self-registers. |
| `tests/test_bench_swebench.py` (create) | load / firewall / prompt / env / diff-split / grade (mocked) tests, with a tiny fake dataset fixture. |

No changes to `base.py` (`EnvSpec` already has `image`/`build_system`/`module_map`), `run.py`, or `config.py` (`BenchmarkCfg` already supports `adapter`/`dataset`/`subset`). The isolation ground-rules from Plan 3's `run_benchmark` already apply to every adapter.

---

## Task 1: `SweBenchAdapter.load` + firewall + registration

**Files:** Create `abench/bench/swebench_java.py`; Modify `abench/bench/__init__.py`; Test `tests/test_bench_swebench.py`.

**Context:** `load` reads the SWE-bench-java JSON array and yields one `Instance` per record. Agent-visible: `problem_statement` (the prompt), `repo`, `instance_id`, `env`. Oracle (grade-only): `base_commit`, `patch`, `test_patch`, `fail_to_pass` (decoded list), `pass_to_pass` (decoded list), `repo`, `version`. `subset` filter: `{repo: "fasterxml/jackson-core"}`. `env` = `EnvSpec(image=_image_ref(repo, version), build_system=<maven|gradle per repo>, module_map={})`. The image ref convention is isolated in `_image_ref` (confirmed against the real registry in the Docker plan; adjust one function if it differs).

- [ ] **Step 1: failing test.** Create `tests/test_bench_swebench.py`:

```python
import json
from pathlib import Path

import abench.bench  # registers adapters
from abench.bench import registry


def _fake_dataset(tmp_path: Path) -> Path:
    """A 2-record SWE-bench-java dataset: one jackson-core, one other repo."""
    records = [
        {
            "repo": "fasterxml/jackson-core",
            "instance_id": "fasterxml__jackson-core-1111",
            "base_commit": "abc123",
            "problem_statement": "NPE in JsonParser when input is empty.",
            "hints_text": "the PR fixed it in ParserBase",   # must NOT reach the agent
            "patch": "diff --git a/src/main/java/A.java ...",   # GOLD
            "test_patch": "diff --git a/src/test/java/ATest.java ...",  # HIDDEN
            "FAIL_TO_PASS": json.dumps(["src:com.fasterxml.jackson.core.ATest"]),
            "PASS_TO_PASS": json.dumps([]),
            "version": "0.1",
        },
        {
            "repo": "google/gson",
            "instance_id": "google__gson-2222",
            "base_commit": "def456",
            "problem_statement": "Gson mishandles nulls.",
            "patch": "diff --git a/gson/src/main/java/B.java ...",
            "test_patch": "diff --git a/gson/src/test/java/BTest.java ...",
            "FAIL_TO_PASS": json.dumps(["gson:com.google.gson.BTest"]),
            "PASS_TO_PASS": json.dumps([]),
            "version": "0.1",
        },
    ]
    f = tmp_path / "swe-bench-java-verified.json"
    f.write_text(json.dumps(records))
    return f


def test_swebench_registered():
    assert "swebench-java" in registry.available()


def test_load_all_instances(tmp_path: Path):
    ds = _fake_dataset(tmp_path)
    adapter = registry.get_adapter("swebench-java")
    insts = list(adapter.load(ds, None))
    assert len(insts) == 2
    ids = {i.instance_id for i in insts}
    assert ids == {"fasterxml__jackson-core-1111", "google__gson-2222"}


def test_load_subset_filters_by_repo(tmp_path: Path):
    ds = _fake_dataset(tmp_path)
    adapter = registry.get_adapter("swebench-java")
    insts = list(adapter.load(ds, {"repo": "fasterxml/jackson-core"}))
    assert len(insts) == 1
    assert insts[0].repo == "fasterxml/jackson-core"


def test_firewall_oracle_holds_gold_and_tests_agentview_does_not(tmp_path: Path):
    ds = _fake_dataset(tmp_path)
    adapter = registry.get_adapter("swebench-java")
    inst = list(adapter.load(ds, {"repo": "fasterxml/jackson-core"}))[0]
    # oracle carries gold/hidden data (grade-only)
    assert inst.oracle["patch"].startswith("diff --git")
    assert inst.oracle["test_patch"].startswith("diff --git")
    assert inst.oracle["base_commit"] == "abc123"
    # F2P/P2P decoded from JSON-encoded STRINGS into real lists
    assert inst.oracle["fail_to_pass"] == ["src:com.fasterxml.jackson.core.ATest"]
    assert inst.oracle["pass_to_pass"] == []
    # firewall: agent_view() has no oracle at all
    assert not hasattr(inst.agent_view(), "oracle")
    # neither gold nor hidden tests nor hints leak into the agent-visible prompt
    prompt = inst.task.prompt_text
    assert "NPE in JsonParser" in prompt                 # the issue IS shown
    assert "ParserBase" not in prompt                    # hints_text NOT shown
    assert "diff --git" not in prompt                    # gold/test patch NOT shown
    assert "ATest" not in prompt                         # FAIL_TO_PASS NOT shown


def test_env_per_instance(tmp_path: Path):
    ds = _fake_dataset(tmp_path)
    adapter = registry.get_adapter("swebench-java")
    inst = list(adapter.load(ds, {"repo": "fasterxml/jackson-core"}))[0]
    assert inst.env.build_system == "maven"              # jackson = maven
    assert inst.env.image == "mswebench/fasterxml_jackson-core:0.1"


def test_load_requires_dataset():
    import pytest
    adapter = registry.get_adapter("swebench-java")
    with pytest.raises(ValueError, match="dataset"):
        list(adapter.load(None, None))
```

- [ ] **Step 2: run, expect FAIL.** `.venv/bin/python -m pytest tests/test_bench_swebench.py -v` → `KeyError: 'swebench-java'` / `ModuleNotFoundError`.

- [ ] **Step 3: implement.** Create `abench/bench/swebench_java.py`:

```python
"""SWE-bench-java adapter (pure-Python core).

Instance = one SWE-bench-java record. The agent gets `problem_statement` + the
repo@base_commit and must produce a source patch; grade splits the agent's diff
(source vs test), delegates the source-diff to the official multi-swe-bench
evaluator (seam `_run_swebench_evaluator`, mocked in tests), and maps the verdict
to GradeResult. Firewall (spec §2): gold `patch`, hidden `test_patch`, and
FAIL_TO_PASS/PASS_TO_PASS live ONLY in `oracle` (grade-only); the AgentView has no
oracle field. `hints_text` is never shown (issue-only fidelity).

DEFERRED to the next plan (Docker): live materialize (repo lives inside the
official image), the real `_run_swebench_evaluator` body + predictions format
(read from the pinned multi-swe-bench repo), scoped-regression, egress-lock."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from . import registry
from .base import Anchors, AgentView, EnvSpec, GradeResult, Instance, TaskSpec

# build_system per repo (verified: 5 Maven + 1 Gradle). Pilot = jackson-core (maven).
_BUILD_SYSTEM: dict[str, str] = {
    "fasterxml/jackson-databind": "maven",
    "fasterxml/jackson-core": "maven",
    "fasterxml/jackson-dataformat-xml": "maven",
    "google/gson": "maven",
    "GoogleContainerTools/jib": "gradle",
    "apache/dubbo": "maven",
}


def _image_ref(repo: str, version: str) -> str:
    """Official multi-swe-bench image ref for a repo@version. Convention isolated
    here; the EXACT registry naming is confirmed against the real images in the
    Docker plan — if it differs, adjust ONLY this function. Used only by the
    deferred Docker materialize/grade, never on the agent path."""
    slug = repo.replace("/", "_")
    return f"mswebench/{slug}:{version}"


def _as_list(value: Any) -> list[str]:
    """FAIL_TO_PASS/PASS_TO_PASS are JSON-encoded STRINGS in the dataset. Decode to
    a real list; tolerate an already-decoded list defensively."""
    if value is None:
        return []
    if isinstance(value, str):
        return list(json.loads(value))
    return list(value)


def _build_prompt(rec: dict) -> str:
    return (
        "Resolve the following issue in this repository. Edit the project's source "
        "files so the issue is fixed; do not modify test files (the evaluation "
        "provides its own tests). Work only from the repository's own code.\n\n"
        "# Issue\n" + (rec.get("problem_statement") or "").strip()
    )


class SweBenchAdapter:
    id = "swebench-java"

    def load(self, dataset: Path | None, subset: dict[str, Any] | None) -> Iterable[Instance]:
        if dataset is None:
            raise ValueError(
                "swebench-java adapter requires 'dataset' (path to swe-bench-java-verified.json)"
            )
        subset = subset or {}
        repo_filter = subset.get("repo")
        records = json.loads(Path(dataset).read_text())
        for rec in records:
            repo = rec["repo"]
            if repo_filter and repo != repo_filter:
                continue
            version = rec.get("version") or ""
            yield Instance(
                instance_id=rec["instance_id"],
                repo=repo,
                task=TaskSpec(prompt_text=_build_prompt(rec)),
                anchors=Anchors(),
                env=EnvSpec(
                    image=_image_ref(repo, version),
                    build_system=_BUILD_SYSTEM.get(repo, "maven"),
                ),
                oracle={
                    "repo": repo,
                    "base_commit": rec["base_commit"],
                    "patch": rec["patch"],
                    "test_patch": rec["test_patch"],
                    "fail_to_pass": _as_list(rec.get("FAIL_TO_PASS")),
                    "pass_to_pass": _as_list(rec.get("PASS_TO_PASS")),
                    "version": version,
                },
            )

    def materialize(self, view: AgentView, workdir: Path) -> None:  # Docker plan
        raise NotImplementedError(
            "SWE-bench-java materialize is Docker-based (repo lives inside the "
            "official image); deferred to the Docker integration plan."
        )

    def grade(self, inst: Instance, source_diff: str, workdir: Path) -> GradeResult:  # Task 3
        raise NotImplementedError


registry.register(SweBenchAdapter())
```

Then append to `abench/bench/__init__.py`:
```python
from . import swebench_java  # noqa: F401  (registers the swebench-java adapter on import)
```

- [ ] **Step 4: run, expect PASS.** `.venv/bin/python -m pytest tests/test_bench_swebench.py -v` (registration + load/firewall/env/prompt/dataset-guard pass; `grade`/`materialize` stubbed until Task 3).

- [ ] **Step 5: no-regression + commit.**
```bash
.venv/bin/python -m pytest tests/test_bench_base.py tests/test_bench_javabench.py tests/test_bench_swebench.py -q
git add abench/bench/swebench_java.py abench/bench/__init__.py tests/test_bench_swebench.py
git commit -m "feat(bench): SWE-bench-java adapter load() + per-instance firewall"
```

---

## Task 2: source/test diff split (`split_source_test_diff`)

**Files:** Modify `abench/bench/swebench_java.py`; Test `tests/test_bench_swebench.py` (append).

**Context:** Spec §7: after the agent finishes, its full unified diff must be split — **source-diff** (non-test files) is the graded prediction; **test-diff** (test files = the agent's own repro) is kept for abench analysis only and **never** sent to grading. This is both an SWE-convention match and a grade-gaming firewall (invariant 2). A file is a "test file" if its path contains a test source root (`src/test/`) or the filename ends in `Test.java`/`Tests.java`/`IT.java` (Maven/Gradle Java conventions). Split by `diff --git` file sections.

- [ ] **Step 1: failing test.** Append to `tests/test_bench_swebench.py`:

```python
import abench.bench.swebench_java as sj


_DIFF = """diff --git a/src/main/java/com/x/A.java b/src/main/java/com/x/A.java
index 111..222 100644
--- a/src/main/java/com/x/A.java
+++ b/src/main/java/com/x/A.java
@@ -1,1 +1,1 @@
-old
+new
diff --git a/src/test/java/com/x/ATest.java b/src/test/java/com/x/ATest.java
index 333..444 100644
--- a/src/test/java/com/x/ATest.java
+++ b/src/test/java/com/x/ATest.java
@@ -1,1 +1,2 @@
 existing
+assertThat(...)
"""


def test_split_source_test_diff():
    source, test = sj.split_source_test_diff(_DIFF)
    # source-diff keeps the main-source file, drops the test file
    assert "src/main/java/com/x/A.java" in source
    assert "ATest.java" not in source
    # test-diff keeps the test file, drops the main-source file
    assert "src/test/java/com/x/ATest.java" in test
    assert "src/main/java/com/x/A.java" not in test


def test_split_empty_and_source_only():
    assert sj.split_source_test_diff("") == ("", "")
    only_src = "diff --git a/src/main/java/A.java b/src/main/java/A.java\n@@ -1 +1 @@\n-a\n+b\n"
    source, test = sj.split_source_test_diff(only_src)
    assert "A.java" in source and test == ""
```

- [ ] **Step 2: run, expect FAIL.** `.venv/bin/python -m pytest tests/test_bench_swebench.py -k split -v` → `AttributeError: split_source_test_diff`.

- [ ] **Step 3: implement.** In `abench/bench/swebench_java.py`, add (module level, after the imports/helpers):

```python
def _is_test_path(path: str) -> bool:
    p = path.replace("\\", "/")
    return (
        "/src/test/" in p
        or p.startswith("src/test/")
        or p.endswith("Test.java")
        or p.endswith("Tests.java")
        or p.endswith("IT.java")
    )


def split_source_test_diff(unified_diff: str) -> tuple[str, str]:
    """Split a unified git diff into (source_diff, test_diff) by per-file section.
    Test files (src/test/ roots, *Test.java/*Tests.java/*IT.java) go to test_diff;
    everything else to source_diff. Only source_diff is ever graded (spec §7)."""
    if not unified_diff.strip():
        return "", ""
    source_parts: list[str] = []
    test_parts: list[str] = []
    current: list[str] = []
    is_test = False

    def _flush() -> None:
        if current:
            (test_parts if is_test else source_parts).append("".join(current))

    for line in unified_diff.splitlines(keepends=True):
        if line.startswith("diff --git "):
            _flush()
            current = [line]
            # "diff --git a/<path> b/<path>" — classify by the b/ path.
            parts = line.split()
            b_path = parts[3][2:] if len(parts) >= 4 and parts[3].startswith("b/") else ""
            is_test = _is_test_path(b_path)
        else:
            current.append(line)
    _flush()
    return "".join(source_parts), "".join(test_parts)
```

- [ ] **Step 4: run, expect PASS.** `.venv/bin/python -m pytest tests/test_bench_swebench.py -v`.

- [ ] **Step 5: commit.**
```bash
git add abench/bench/swebench_java.py tests/test_bench_swebench.py
git commit -m "feat(bench): SWE-bench-java source/test diff split (never grade test edits)"
```

---

## Task 3: `grade` — DUAL grading (official verdict + abench's own methodology), both via mocked seams

**Files:** Modify `abench/bench/swebench_java.py`; Test `tests/test_bench_swebench.py` (append).

**Context (spec §7 — the two graders are CO-EQUAL, first-class):** `grade` receives the agent's full workdir diff (as `source_diff` per the `BenchmarkAdapter` protocol — it is the full diff; the SWE adapter splits it here). It runs BOTH graders on the same run:

1. **Official verdict (comparability — spec §3):** delegate the **source-diff only** to the pinned, offline multi-swe-bench evaluator via seam `_run_swebench_evaluator(oracle, source_diff) -> dict` → `resolved` (the leaderboard-comparable number, source of truth). This is JavaBench's `_run_javabench_grader` analog.
2. **abench's OWN methodology (the richer picture — spec §7, the same kind abench runs on the putValue experiment):** the official criterion has NO regression guard (`PASS_TO_PASS` empty for all 91), so abench adds its own analysis via seam `_run_abench_verify(oracle, source_diff, test_diff, workdir) -> dict` → `{scoped_regressions, repro_reproduced, abench_resolved, ...}` (blast-radius regression tests before/after; did the agent's own repro fail on base; abench's own pass/fail as a cross-check).

Both seams are **mocked in this task** (their live bodies need the build environment = Docker + graph/Joern — the next plan). The result carries BOTH: `official_report` = raw evaluator dict; `abench` = abench's methodology dict + the cheap-here stats (`test_diff_present`, `n_fail_to_pass`). NOTE: the agent-run metrics (tokens, tool-calls, steps, diff-size, cheating signals) are abench's methodology too and **already flow** via `run_benchmark` → `extract(result.trace, …)` (Plan 2) — `GradeResult.abench` here is the grading-side complement, not the whole of it. `resolved` (headline) comes ONLY from the official verdict; `abench_resolved` is abench's separate, clearly-labelled cross-check, never exported as the SWE number.

- [ ] **Step 1: failing test.** Append to `tests/test_bench_swebench.py`:

```python
def _prep(tmp_path):
    ds = _fake_dataset(tmp_path)
    adapter = registry.get_adapter("swebench-java")
    inst = list(adapter.load(ds, {"repo": "fasterxml/jackson-core"}))[0]
    workdir = tmp_path / "wd"
    workdir.mkdir()
    return adapter, inst, workdir


_AGENT_DIFF = (
    "diff --git a/src/main/java/A.java b/src/main/java/A.java\n@@ -1 +1 @@\n-a\n+b\n"
    "diff --git a/src/test/java/ATest.java b/src/test/java/ATest.java\n@@ -1 +1,2 @@\n x\n+y\n"
)


def _mock_both_graders(monkeypatch, *, official_resolved, seen=None,
                       abench_ret=None):
    """Mock BOTH grade seams. `seen` (if given) captures what the official
    evaluator received, to prove only the source-diff is sent."""
    def _fake_official(oracle, source_diff):
        if seen is not None:
            seen["source_diff"] = source_diff
        return {"resolved": official_resolved, "report": {}}
    monkeypatch.setattr(sj, "_run_swebench_evaluator", _fake_official)
    monkeypatch.setattr(
        sj, "_run_abench_verify",
        lambda oracle, source_diff, test_diff, workdir: (
            abench_ret if abench_ret is not None
            else {"scoped_regressions": [], "repro_reproduced": True,
                  "abench_resolved": official_resolved}))


def test_grade_official_verdict_and_source_only_delegation(tmp_path, monkeypatch):
    adapter, inst, workdir = _prep(tmp_path)
    seen = {}
    _mock_both_graders(monkeypatch, official_resolved=True, seen=seen)
    g = adapter.grade(inst, _AGENT_DIFF, workdir)
    # headline verdict = OFFICIAL only
    assert g.resolved is True
    assert g.standard_protocol is True
    assert g.evaluator.startswith("multi-swe-bench")
    assert g.official_report["resolved"] is True
    # only the SOURCE diff reached the official evaluator — the agent's test edit
    # is stripped (firewall / no grade-gaming)
    assert "src/main/java/A.java" in seen["source_diff"]
    assert "ATest.java" not in seen["source_diff"]


def test_grade_carries_abench_own_methodology(tmp_path, monkeypatch):
    adapter, inst, workdir = _prep(tmp_path)
    _mock_both_graders(monkeypatch, official_resolved=True, abench_ret={
        "scoped_regressions": ["com.x.OtherTest#t"], "repro_reproduced": True,
        "abench_resolved": False})
    g = adapter.grade(inst, _AGENT_DIFF, workdir)
    # dual-grading: abench's OWN methodology is first-class, alongside official
    assert g.abench["scoped_regressions"] == ["com.x.OtherTest#t"]
    assert g.abench["repro_reproduced"] is True
    assert g.abench["abench_resolved"] is False        # abench's separate cross-check
    assert g.abench["test_diff_present"] is True        # agent wrote a repro test
    assert g.abench["n_fail_to_pass"] == 1
    # abench's cross-check verdict must NOT override the exported (official) number
    assert g.resolved is True


def test_grade_not_resolved(tmp_path, monkeypatch):
    adapter, inst, workdir = _prep(tmp_path)
    _mock_both_graders(monkeypatch, official_resolved=False)
    g = adapter.grade(inst, _AGENT_DIFF, workdir)
    assert g.resolved is False
    assert g.standard_protocol is True
```

- [ ] **Step 2: run, expect FAIL.** `.venv/bin/python -m pytest tests/test_bench_swebench.py -k grade -v` → `AttributeError` (the tests `monkeypatch.setattr(sj, "_run_swebench_evaluator"/"_run_abench_verify", …)` on names that don't exist yet) / `NotImplementedError`.

- [ ] **Step 3: implement.** In `abench/bench/swebench_java.py` add BOTH grade seams (module level) and the `grade` body.

Add near the top (after `_image_ref`):
```python
_EVALUATOR_PIN = "multi-swe-bench@<pin-set-in-docker-plan>"


def _run_swebench_evaluator(oracle: dict, source_diff: str) -> dict:
    """Delegate to the official multi-swe-bench evaluator in a clean, OFFLINE
    grading container: apply `source_diff` + the oracle's own `test_patch` to a
    pristine checkout at `base_commit`, run FAIL_TO_PASS/PASS_TO_PASS, return the
    raw report incl. a top-level `resolved: bool`. Isolated so tests monkeypatch it.

    DEFERRED (Docker plan): the real body. IMPLEMENTER of the Docker plan MUST read
    the pinned multi-swe-bench repo to confirm the exact predictions-file format and
    CLI/entry (spec §10 open question), set `_EVALUATOR_PIN` to the pinned digest,
    and run it with no network (offline determinism, spec §7)."""
    raise NotImplementedError(
        "live SWE-bench-java grading is Docker-based; deferred to the Docker plan"
    )


def _run_abench_verify(oracle: dict, source_diff: str, test_diff: str, workdir: Path) -> dict:
    """abench's OWN grading methodology — run ALONGSIDE the official verdict (spec
    §7), the same kind abench already runs on the putValue experiment. The official
    criterion has NO regression guard (PASS_TO_PASS empty) — this is what abench
    adds. Returns {scoped_regressions: list[str], repro_reproduced: bool,
    abench_resolved: bool|None}. Isolated so tests monkeypatch it.

    DEFERRED (Docker plan): the real body = in a clean container, apply the
    source-fix, run the BLAST-RADIUS tests (touched methods → covering tests via the
    graph/Joern, spec §7) before/after to find regressions; re-run the agent's own
    repro (from test_diff) on base for repro_reproduced; abench_resolved = abench's
    own FAIL_TO_PASS pass/fail cross-check. Docker + graph gated."""
    raise NotImplementedError(
        "abench's own SWE verify/regression is Docker+graph-based; deferred to the Docker plan"
    )
```

Replace `grade`'s body:
```python
    def grade(self, inst: Instance, source_diff: str, workdir: Path) -> GradeResult:
        # `source_diff` here is the agent's FULL workdir diff (protocol name). Split
        # it: only the source part is graded; the agent's own test edits are kept
        # for abench stats but NEVER sent to the evaluator (spec §7, invariant 2).
        src_diff, test_diff = split_source_test_diff(source_diff)
        # (1) OFFICIAL verdict — the comparable, exported number (spec §3).
        official = _run_swebench_evaluator(inst.oracle, src_diff)
        # (2) abench's OWN methodology — regressions/repro the official criterion
        # omits (spec §7). Co-equal, but NEVER the exported SWE number.
        own = _run_abench_verify(inst.oracle, src_diff, test_diff, workdir)
        return GradeResult(
            resolved=bool(official.get("resolved")),      # headline = OFFICIAL only
            evaluator=_EVALUATOR_PIN,
            standard_protocol=True,
            official_report=official,
            abench={
                **own,                                      # scoped_regressions, repro_reproduced, abench_resolved
                "test_diff_present": bool(test_diff.strip()),
                "n_fail_to_pass": len(inst.oracle.get("fail_to_pass") or []),
            },
        )
```

- [ ] **Step 4: run, expect PASS.** `.venv/bin/python -m pytest tests/test_bench_swebench.py -v` (all pass; grade tests use the monkeypatched evaluator).

- [ ] **Step 5: no-regression + commit.**
```bash
.venv/bin/python -m pytest tests/test_bench_base.py tests/test_bench_javabench.py tests/test_bench_swebench.py -q
git add abench/bench/swebench_java.py tests/test_bench_swebench.py
git commit -m "feat(bench): SWE-bench-java dual grade — official evaluator + abench methodology seams"
```

**NEXT PLAN (Docker integration) — not part of this suite:** clone the pinned multi-swe-bench repo + read the real evaluator (resolve spec §10: predictions format, CLI/Docker driver); install Docker + pull the jackson-core official image; implement `materialize` (agent-run container from the image) and BOTH live grade bodies with exact code — (1) `_run_swebench_evaluator` (clean grading container, offline, official verdict) and (2) `_run_abench_verify` (abench's own blast-radius regression via graph/Joern + repro re-run); set `_EVALUATOR_PIN`; validate end-to-end on 1–2 jackson-core instances against the official grader (spec §9 Phase-1 success). Then: egress-lock (§5, Plan 5), remaining 5 repos.

**Final-review notes for the Docker plan (opus, 2026-07-06):**
1. **`load()` runs OUTSIDE `run_benchmark`'s per-run safety net** (`abench/bench/run.py:46` calls `adapter.load(...)` before the per-instance `try`). A single malformed record — a bad `_as_list` value or a missing `rec["base_commit"]`/`rec["patch"]` — aborts the whole 91-instance sweep before any instance runs (pre-existing property, shared with `javabench.py`; the `_as_list` non-list guard slightly widens the raise surface — deliberately, loud > silent on bad data). Before the first real 91-instance run, either add per-record tolerance in `load` or validate the dataset up front.
2. **`_is_test_path` false-positive (safe-side):** a real production source file under `src/main/**` literally named `*Test.java`/`*Tests.java`/`*IT.java` classifies as TEST and is dropped from the graded source-diff → would grade unresolved. Vanishingly rare in Java `src/main`; watch for it during the jackson end-to-end spot-check.
3. `_run_swebench_evaluator`'s live body must honor the `resolved: bool` contract (`grade` does `bool(official.get("resolved"))` — a non-bool truthy like `"yes"` would pass through).

---

## Self-review

**Spec coverage:** §4 adapter seam + firewall (Task 1: `oracle` holds gold/tests, `agent_view()` excludes it); §2 invariants 1–4 (Task 1 prompt is issue-only, no hints/gold/tests; Task 3 `standard_protocol` + pin); §7 dual-grading + diff-split (Tasks 2–3: source graded, test stripped, and BOTH graders are first-class — `official_report` from the official evaluator seam AND `abench` from the abench-methodology seam `_run_abench_verify`, headline `resolved` = official only). The LIVE bodies of BOTH grade seams (Docker + graph/Joern), Docker isolation (§5), egress-lock (§5), tipper (§6) are explicitly deferred with named seams; the agent-run metrics half of abench's methodology already flows via `run_benchmark` (Plan 2).

**Placeholder scan:** the pure-Python parts (Tasks 1–2, grade mapping in Task 3) are complete exact code. Two deferred integration points are named + located + isolated behind seams with mock-based unit tests, not vague TODOs: `_run_swebench_evaluator` (real body + `_EVALUATOR_PIN` in the Docker plan, after reading the pinned repo) and `_image_ref` (registry-naming convention, one function to adjust). `materialize` is an explicit Docker-deferred stub. These mirror Plan 3's confirmed pattern (`_run_javabench_grader`).

**Firewall:** `oracle` = {repo, base_commit, patch, test_patch, fail_to_pass, pass_to_pass, version}; `agent_view()` structurally excludes it (Plan 1 `AgentView` has no `oracle` field). Test `test_firewall_…` asserts gold/test/hints absent from `prompt_text` and `agent_view()`. The diff-split (Task 2) is the second firewall: the agent's test edits never reach grading (Task 3 asserts `ATest.java` absent from the delegated source-diff).

**Type/name consistency:** `SweBenchAdapter.{load,materialize,grade}` matches the Plan 1 `BenchmarkAdapter` protocol and Plan 2 `run_benchmark` grade→`verify_status` mapping. `GradeResult(resolved, evaluator, standard_protocol, official_report, abench)`, `oracle` keys, `split_source_test_diff(str)->tuple[str,str]`, `_run_swebench_evaluator(oracle, source_diff)->dict`, `_run_abench_verify(oracle, source_diff, test_diff, workdir)->dict` used identically across tasks and tests. `EnvSpec(image, build_system)` uses existing fields (no `base.py` change).

**Risk:** only additive — one new adapter file + one `__init__.py` import; no shared-file behavior change (unlike Plan 3, no `base.py`/`run.py` edits). `materialize` stub means this adapter cannot yet run end-to-end through `run_benchmark` (needs the Docker plan) — deliberate; the core is unit-tested in isolation, exactly as Plan 3's load/grade were before its materialize/host steps.
