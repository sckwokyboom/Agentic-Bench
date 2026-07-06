# Universal Benchmark Layer — Phase 1, Plan 4b: SWE-bench-java Docker Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `swebench-java` adapter actually RUN end-to-end against the official multi-swe-bench evaluator on the jackson-core pilot — by (1) reworking the merged pure-Python core (Plan 4) from the assumed *flat* HF schema to the **native Multi-SWE-bench `Dataset` schema** the real evaluator consumes, (2) implementing live Docker `materialize`, (3) implementing both live grade-seam bodies (`_run_swebench_evaluator` → official verdict via `run_evaluation.py`; `_run_abench_verify` → abench's regression/repro methodology extracted from the harness's own per-instance report), and (4) a prepared-host setup + end-to-end validation on 1–2 jackson-core instances.

**Architecture:** The official harness (`multi-swe-bench`, pinned) is the source of truth. Its `run_evaluation.py` consumes a NATIVE `Dataset` JSONL and a prediction JSONL of `{org, repo, number, fix_patch}`, builds/uses a per-PR Docker image `mswebench/<org>_m_<repo>:pr-<number>` (repo + `test_patch` baked in), applies the candidate's `fix_patch` in a clean container, runs `mvn clean test`, and writes `final_report.json` with `resolved_ids`. So: `load` reads the native dataset; `materialize` extracts repo@base from the image so the agent edits a host workdir; `grade` splits the agent diff (source vs test — the source part IS the `fix_patch`), delegates the source-diff to the harness (official verdict) AND to abench's own report-reader (regression/repro), and maps both to `GradeResult`.

**Tech Stack:** Python ≥3.12 (venv 3.14), pydantic v2, pytest. Live: Docker Desktop (macOS — installable on this host), the pinned multi-swe-bench harness, the jackson-core official image.

**Ground truth (from the 2026-07-06 spike; see memory `multi-swe-bench-evaluator-interface`):**
- Harness repo `github.com/multi-swe-bench/multi-swe-bench`, **pin HEAD `24f493f8a103e72312ded4f6b9c89f081d69cb09`, setup.py version `1.1.0`**.
- **Eval:** `python -m multi_swe_bench.harness.run_evaluation --config <c.json>`. Required config keys: `workdir`, `patch_files` (glob→prediction JSONL), `dataset_files` (glob→native dataset JSONL), `log_dir`; `output_dir` + `repo_dir` for `mode="evaluation"` (default). `specifics` scopes to one instance by id substring. Writes `output_dir/final_report.json`. Config is STRICT — unknown keys raise; keys = exactly the argparse flags.
- **Prediction record = `{org, repo, number, fix_patch}`** (JSONL, one per line). NO `instance_id`, NO `test_patch`. Candidate supplies ONLY `fix_patch` (its source-diff); `test_patch` is baked into the image from the dataset. → validates our source/test diff-split.
- **Native `Dataset` record:** `org:str`, `repo:str`, `number:int`, `state/title/body`, `base:{label,ref,sha}` (commit = `base.sha`), `resolved_issues:[{number,title,body}]`, `fix_patch:str`, `test_patch:str`, `f2p_tests`/`p2p_tests`/`s2p_tests`/`n2p_tests:dict[str,Test]` (Test = `{run,test,fix}` statuses), and REQUIRED non-null `run_result`/`test_patch_result`/`fix_patch_result:TestResult` (`{passed_count,failed_count,skipped_count,passed_tests,failed_tests,skipped_tests}`). We use records from the official HF dataset verbatim (do NOT synthesize these).
- **Image:** `mswebench/<org>_m_<repo>:pr-<number>` (lowercased, `_m_` separator). Literal for pilot e.g. `mswebench/fasterxml_m_jackson-core:pr-964`. No auto-`docker pull` in the harness (local-exists check → build-from-scratch if absent); pre-pull via `bash scripts/download_images.sh scripts/images_verified.txt` for offline. `__main__` also ensures a `mswebench/nix_swe:v1.0` helper container.
- **Resolved:** `Report.check()` (no PASS→FAIL regression + ≥1 fail/skip→pass + no anomalous pattern), self-derived per run; `final_report.json` → `resolved_ids`/`unresolved_ids`/`error_ids` (ids = `org/repo:pr-N`). Per-instance `report.json` carries `p2p_tests`/`f2p_tests`/`valid`/`error_msg` — abench reads THIS for regression/repro.

**Spec:** `docs/superpowers/specs/2026-07-01-universal-benchmark-layer-design.md` (§4 firewall, §5 isolation, §7 dual-grading, §9 Phase-1 success, §10 open questions — now RESOLVED). Builds on Plan 4 core (merged `main` @ `2270701`): `abench/bench/swebench_java.py` + tests. Reuses the split-diff firewall + dual-seam grade shape (both unchanged in intent; field mapping + seam bodies change).

**Decision (user, 2026-07-06):** consume the NATIVE ByteDance Multi-SWE-bench Java dataset directly (the evaluator's source of truth), NOT the flat `swe-bench-java-verified.json` — avoids a fragile flat→native translation that would have to synthesize the required `TestResult` objects.

**Branch:** create `feat/swebench-docker` off `main` before Task 1.

**Test command:** `.venv/bin/python -m pytest <path> -v` from repo root `/Users/sckwoky/Projects/Agentic-Bench`. Live steps (Task 5) run on this host with Docker.

**Explicitly DEFERRED (not here):** egress-lock (spec §5, Plan 5); the Joern/graph BLAST-RADIUS scoping of abench regressions (this plan's `_run_abench_verify` v1 reads the harness's own report — the full method→covering-test graph scoping is a later enhancement); the tipper (§6, Phase 2); the other 5 repos (jackson-core pilot only here).

---

## File structure

| File | Responsibility |
|------|----------------|
| `abench/bench/swebench_java.py` (modify) | `load`/`_image_ref`/`_build_prompt`/`oracle` reworked to native schema; `materialize` (docker-cp repo from image); `_run_swebench_evaluator` + `_run_abench_verify` live bodies. `split_source_test_diff` + the dual `grade` assembly UNCHANGED. |
| `abench/bench/_msb.py` (create) | Small helper module: native-record field accessors (`org`/`repo`/`number`/`base_sha`/`image_ref`/`instance_id`), the `run_evaluation` subprocess driver, and the `final_report.json`/`report.json` readers. Keeps `swebench_java.py` focused and the subprocess/docker seams isolated for mocking. |
| `tests/test_bench_swebench.py` (modify) | Rework the fixture to a native record; update load/firewall/env/grade tests; add materialize + evaluator-driver + report-reader tests (docker/subprocess mocked). |

No `base.py`/`run.py`/`config.py` changes (the `BenchmarkAdapter` seam + dual-grading `GradeResult` already fit).

---

## Task 1: Rework `load` + `oracle` + `_image_ref` + `_build_prompt` to the native schema

**Files:** Modify `abench/bench/swebench_java.py`; create `abench/bench/_msb.py`; Test `tests/test_bench_swebench.py` (rework fixture + load/firewall/env tests).

**Context:** Plan 4 core built `load` around the flat HF schema (`repo`, `instance_id`, `base_commit`, `patch`, `FAIL_TO_PASS` lists). The real evaluator consumes the native `Dataset` schema. Rework `load` to read native records: `org`+`repo` (join to `repo="<org>/<repo>"` for display), `number`, `base.sha`, `fix_patch` (gold), `test_patch` (hidden), `f2p_tests`/`p2p_tests` (dicts), and the required `TestResult` objects (carried verbatim in `oracle` for grade — we pass the whole record back to the harness, not reconstruct it). Prompt = the issue text composed from `title`+`body`+`resolved_issues` (canonical SWE input; still issue-only, no gold/tests/hints). `env.image = mswebench/<org>_m_<repo>:pr-<number>`. Firewall unchanged: gold `fix_patch` + hidden `test_patch`/`f2p_tests` live ONLY in `oracle`.

`abench/bench/_msb.py` holds the native-record accessors so the schema knowledge is in one place:

```python
"""Multi-SWE-bench native-format helpers (schema + evaluator driver + report reader).
Pinned harness: github.com/multi-swe-bench/multi-swe-bench @ 24f493f8 (v1.1.0)."""
from __future__ import annotations

from typing import Any


def instance_id(rec: dict) -> str:
    """The harness's id: 'org/repo:pr-<number>'."""
    return f"{rec['org']}/{rec['repo']}:pr-{rec['number']}"


def display_repo(rec: dict) -> str:
    return f"{rec['org']}/{rec['repo']}"


def base_sha(rec: dict) -> str:
    return rec["base"]["sha"]


def image_ref(rec: dict) -> str:
    """Official per-PR image: mswebench/<org>_m_<repo>:pr-<number> (lowercased)."""
    return f"mswebench/{rec['org']}_m_{rec['repo']}:pr-{rec['number']}".lower()


def issue_text(rec: dict) -> str:
    """Canonical issue text: title + body + linked resolved-issue bodies. No gold,
    no tests, no hints (issue-only fidelity, spec §2)."""
    parts: list[str] = []
    if rec.get("title"):
        parts.append(rec["title"].strip())
    if rec.get("body"):
        parts.append(rec["body"].strip())
    for iss in rec.get("resolved_issues") or []:
        t, b = (iss.get("title") or "").strip(), (iss.get("body") or "").strip()
        if t or b:
            parts.append((t + "\n" + b).strip())
    return "\n\n".join(p for p in parts if p)


def prediction_record(rec: dict, fix_patch: str) -> dict[str, Any]:
    """The evaluator's prediction JSONL record — {org, repo, number, fix_patch} ONLY."""
    return {"org": rec["org"], "repo": rec["repo"], "number": rec["number"], "fix_patch": fix_patch}
```

- [ ] **Step 1: failing test.** Rework the fixture + firewall/env tests in `tests/test_bench_swebench.py` to a native record (replace `_fake_dataset`):

```python
def _fake_dataset(tmp_path: Path) -> Path:
    """A 1-record NATIVE Multi-SWE-bench dataset (jackson-core)."""
    rec = {
        "org": "fasterxml", "repo": "jackson-core", "number": 964,
        "state": "closed", "title": "NPE in JsonParser on empty input",
        "body": "Parsing an empty string throws NullPointerException.",
        "base": {"label": "fasterxml:2.x", "ref": "2.x", "sha": "abc123"},
        "resolved_issues": [{"number": 963, "title": "NPE empty input", "body": "see title"}],
        "fix_patch": "diff --git a/src/main/java/A.java b/src/main/java/A.java\n@@ -1 +1 @@\n-a\n+b\n",   # GOLD
        "test_patch": "diff --git a/src/test/java/ATest.java ...\n",                                       # HIDDEN
        "f2p_tests": {"com.fasterxml.jackson.core.ATest": {"run": "PASS", "test": "FAIL", "fix": "PASS"}},
        "p2p_tests": {}, "s2p_tests": {}, "n2p_tests": {}, "fixed_tests": {},
        "run_result": {"passed_count": 1, "failed_count": 0, "skipped_count": 0,
                       "passed_tests": ["com.x.T"], "failed_tests": [], "skipped_tests": []},
        "test_patch_result": {"passed_count": 0, "failed_count": 1, "skipped_count": 0,
                              "passed_tests": [], "failed_tests": ["com.fasterxml.jackson.core.ATest"], "skipped_tests": []},
        "fix_patch_result": {"passed_count": 1, "failed_count": 0, "skipped_count": 0,
                             "passed_tests": ["com.fasterxml.jackson.core.ATest"], "failed_tests": [], "skipped_tests": []},
    }
    f = tmp_path / "java-verified.jsonl"
    f.write_text(json.dumps(rec) + "\n")
    return f


def test_load_native_instance(tmp_path: Path):
    ds = _fake_dataset(tmp_path)
    adapter = registry.get_adapter("swebench-java")
    inst = list(adapter.load(ds, {"repo": "fasterxml/jackson-core"}))[0]
    assert inst.instance_id == "fasterxml/jackson-core:pr-964"
    assert inst.repo == "fasterxml/jackson-core"
    assert inst.env.build_system == "maven"
    assert inst.env.image == "mswebench/fasterxml_m_jackson-core:pr-964"
    # firewall: gold + hidden tests only in oracle
    assert inst.oracle["fix_patch"].startswith("diff --git")
    assert inst.oracle["test_patch"].startswith("diff --git")
    assert inst.oracle["base_sha"] == "abc123"
    assert "com.fasterxml.jackson.core.ATest" in inst.oracle["f2p_tests"]
    assert not hasattr(inst.agent_view(), "oracle")
    # prompt = issue only; no gold/tests/hidden
    p = inst.task.prompt_text
    assert "NPE in JsonParser" in p and "empty" in p.lower()
    assert "diff --git" not in p and "ATest" not in p
    # oracle carries the full native record for the grader + the harness root
    assert inst.oracle["record"]["number"] == 964
```

(Also update the earlier `test_load_subset_filters_by_repo`/`test_env_per_instance`/firewall tests to the native record + the `_m_`/`pr-964` image; `subset` filter now matches on `display_repo(rec)`.)

- [ ] **Step 2: run, expect FAIL.** `.venv/bin/python -m pytest tests/test_bench_swebench.py -k "native or load or env or firewall" -v` → assertions fail (old flat-schema load).

- [ ] **Step 3: implement.** Create `abench/bench/_msb.py` (above). In `swebench_java.py`: `import` the `_msb` helpers; replace `_image_ref` usage with `_msb.image_ref`; replace `_build_prompt` with `_msb.issue_text`; drop `_as_list` (native `f2p_tests` are already dicts). Rework `load`:

```python
    def load(self, dataset, subset):
        if dataset is None:
            raise ValueError("swebench-java adapter requires 'dataset' (native Multi-SWE-bench JSONL)")
        subset = subset or {}
        repo_filter = subset.get("repo")
        msb_root = subset.get("msb_root")   # path to the pinned multi-swe-bench checkout (grade needs it)
        for line in Path(dataset).read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if repo_filter and _msb.display_repo(rec) != repo_filter:
                continue
            yield Instance(
                instance_id=_msb.instance_id(rec),
                repo=_msb.display_repo(rec),
                task=TaskSpec(prompt_text=(
                    "Resolve the following issue in this repository. Edit the project's "
                    "SOURCE files so the issue is fixed; do not modify test files (the "
                    "evaluation provides its own). Work only from the repo's own code.\n\n"
                    "# Issue\n" + _msb.issue_text(rec))),
                anchors=Anchors(),
                env=EnvSpec(image=_msb.image_ref(rec), build_system="maven"),
                oracle={
                    "record": rec,                 # full native record → grader writes it back verbatim
                    "base_sha": _msb.base_sha(rec),
                    "fix_patch": rec["fix_patch"],
                    "test_patch": rec["test_patch"],
                    "f2p_tests": rec.get("f2p_tests") or {},
                    "msb_root": msb_root,
                },
            )
```

- [ ] **Step 4: run, expect PASS.** `.venv/bin/python -m pytest tests/test_bench_swebench.py -v` (load/firewall/env/diff-split/grade-mock tests pass; grade tests still use mocked seams — unchanged from Plan 4 core).

- [ ] **Step 5: commit.** `git add abench/bench/swebench_java.py abench/bench/_msb.py tests/test_bench_swebench.py && git commit -m "feat(bench): swebench-java load reworked to native Multi-SWE-bench schema (org/repo/number, _m_ image, issue-from-title/body)"`

---

## Task 2: `materialize` — extract repo@base from the official image (Docker)

**Files:** Modify `abench/bench/swebench_java.py`; add a `_docker_cp_repo` seam to `abench/bench/_msb.py`; Test `tests/test_bench_swebench.py`.

**Context:** The agent edits a host workdir. The official image `mswebench/<org>_m_<repo>:pr-<number>` has the repo checked out at `base.sha` under `/home/<repo>`. `materialize` creates a throwaway container from the image, `docker cp`s `/home/<repo>` to the workdir, removes the container, strips `.git`. The docker calls are isolated in `_msb._docker_cp_repo` (mocked in tests; live needs Docker). If the image is absent locally, surface a clear error telling the user to pre-pull (`download_images.sh`).

- [ ] **Step 1: failing test** (mock `_msb._docker_cp_repo` to lay down a fake tree; assert workdir gets the repo, `.git` stripped). — full test code in the implementer prompt.
- [ ] **Step 2: run, expect FAIL** (`NotImplementedError`).
- [ ] **Step 3: implement** `_docker_cp_repo(image, container_src, dest)` (`docker create` → `docker cp` → `docker rm`, via `subprocess`/`sys.executable`-independent `docker` CLI; clear error if image missing) + `materialize` calling it then stripping `.git`.
- [ ] **Step 4: run, expect PASS.**
- [ ] **Step 5: commit** `"feat(bench): swebench-java materialize via docker cp of repo@base from the official image"`.

---

## Task 3: `_run_swebench_evaluator` live — drive `run_evaluation.py`, read `resolved_ids`

**Files:** Modify `abench/bench/swebench_java.py` (the seam body) + `abench/bench/_msb.py` (the driver); Test `tests/test_bench_swebench.py`.

**Context:** The seam writes, into a temp dir: (a) `dataset.jsonl` = the oracle's full native `record` (one line), (b) `preds.jsonl` = `_msb.prediction_record(record, source_diff)` (the agent's SOURCE diff as `fix_patch`), (c) `config.json` with `mode:"evaluation"`, `workdir`/`log_dir`/`output_dir`, `patch_files:[preds]`, `dataset_files:[dataset]`, `specifics:[instance_id]`, `repo_dir` (a dir holding the extracted repo, reuse the materialized workdir's parent or re-extract), `need_clone:false`, `force_build:false`. Runs `python -m multi_swe_bench.harness.run_evaluation --config config.json` with `cwd=<msb_root>` (the pinned checkout), reads `output_dir/final_report.json`, returns `{"resolved": instance_id in resolved_ids, "report": final_report}`. Subprocess isolated in `_msb.run_evaluation(...)` (mocked in tests).

- [ ] Steps 1–5 (TDD): failing test mocks `_msb.run_evaluation` to return a fake `final_report` with the id in `resolved_ids` → assert `grade().resolved is True`; a second with it in `unresolved_ids` → `False`. Implement `_msb.run_evaluation(msb_root, config)` (write config, `subprocess.run([python,"-m","multi_swe_bench.harness.run_evaluation","--config",cfg], cwd=msb_root, check=True)`, read `final_report.json`) + the seam body assembling the three files and mapping. Commit `"feat(bench): swebench-java official grade via run_evaluation.py (resolved_ids)"`.

**HOST note:** the exact `resolved`-id string must equal `_msb.instance_id(rec)` (`org/repo:pr-N`) — confirm against a real `final_report.json` in Task 5.

---

## Task 4: `_run_abench_verify` live v1 — regression/repro from the harness's own report

**Files:** Modify `abench/bench/swebench_java.py` (seam body) + `abench/bench/_msb.py` (report reader); Test `tests/test_bench_swebench.py`.

**Context:** The harness already computes, per instance, `report.json` with `p2p_tests`/`f2p_tests`/`valid`/`error_msg` (its `Report.check()` detects PASS→FAIL regressions — the exact thing the official empty-PASS_TO_PASS criterion omits and abench adds). v1 of abench's methodology READS that report (no separate Joern run — deferred): `scoped_regressions` = tests that were PASS pre-fix and FAIL post-fix (from the report's status maps / `error_msg`), `repro_reproduced` = whether the oracle's `f2p_tests` actually failed at the `test` stage, `abench_resolved` = the harness `valid` flag (abench's own read of the same run). Report path isolated in `_msb.read_instance_report(msb_root, workdir_layout, instance_id)`.

- [ ] Steps 1–5 (TDD): failing test mocks `_msb.read_instance_report` to return a report with a PASS→FAIL test → assert `grade().abench["scoped_regressions"]` contains it and `abench_resolved` reflects `valid`. Implement the reader + seam body. Commit `"feat(bench): swebench-java abench methodology v1 — regressions/repro from harness report"`.

**Deferred enhancement (later):** replace v1's "read the harness report" with the graph/Joern blast-radius scoping (method→covering-tests) from spec §7 — a bigger piece; v1 is a real, correct subset (the harness runs the relevant suite; v1 surfaces its regressions).

---

## Task 5: Prepared-host setup + end-to-end validation (jackson-core pilot)

**Files:** none in `abench/` (this is host setup + a validation run); record results in the plan/memory.

**Context:** This runs on THIS macOS host (Docker installable). NOT part of the unit suite.

- [ ] **Install Docker** (`brew install --cask docker` then launch Docker Desktop, or the user installs it) — confirm `docker version` shows a running daemon.
- [ ] **Clone + pin the harness:** `git clone github.com/multi-swe-bench/multi-swe-bench`, `git checkout 24f493f8a103e72312ded4f6b9c89f081d69cb09`; `pip install -e .` (or add to the venv). Record the path as `msb_root`.
- [ ] **Get the native jackson-core dataset:** download the Java split from HF `ByteDance-Seed/Multi-SWE-bench`, extract jackson-core records to a native `.jsonl`. Confirm the real record fields match `_msb`'s accessors (esp. `base.sha`, `f2p_tests` shape) — fix `_msb` if reality differs (that's the point of this step).
- [ ] **Pre-pull the pilot image:** `bash scripts/download_images.sh scripts/images_verified.txt` (or pull just `mswebench/fasterxml_m_jackson-core:pr-<N>` + `:base` + `mswebench/nix_swe:v1.0`).
- [ ] **End-to-end on 1–2 instances:** run `abench run` on a `benchmark: {adapter: swebench-java, dataset: <native.jsonl>, subset: {repo: fasterxml/jackson-core, msb_root: <path>}}` experiment with a real model (baseline condition). Confirm `grade.json`/`benchmark_summary.json` produced; `official.resolved` matches a manual `run_evaluation.py` spot-check on the same prediction; `abench.scoped_regressions`/`repro_reproduced` populated.
- [ ] **Record** the confirmed facts (real image tag, dataset field reality, `resolved`-id format, timing) back into the plan + memory `multi-swe-bench-evaluator-interface`.

**MUST-CONFIRM before trusting the verdict (from the opus final review) — these could SILENTLY mis-grade, not crash, so spot-check them explicitly (a green end-to-end is not enough):**
- [ ] **(a) `resolved_ids` byte-equal to `_msb.instance_id(rec)`** (`org/repo:pr-N`, INCLUDING case). The join `iid in resolved_ids` (swebench_java.py) is exact-match; if the harness lowercases ids (the image tag is lowercased) a real fix would false-grade as unresolved. jackson-core is all-lowercase so the pilot is safe, but confirm before scaling to mixed-case repos (jib=`GoogleContainerTools`). If they differ, normalize the join.
- [ ] **(b) per-instance `report.json` LOCATION** — `_msb.find_instance_report` globs the harness `workdir`. If the harness writes it under `log_dir`/`output_dir` instead, the glob returns `{}` and the ENTIRE abench plane silently zeroes (`scoped_regressions=[]`, `abench_resolved=None`) — indistinguishable from a clean run. The grade output now carries `abench["report_found"]` — **confirm it is `true` on the first real run**; if `false`, fix `find_instance_report`'s root before trusting `abench.*`.
- [ ] **(c) report shape** — the per-instance report actually carries `p2p_tests`/`f2p_tests` dicts of `{run,test,fix}` + a `valid` flag (the shape `_run_abench_verify` assumes). Spot-check one report.json.
- [ ] **(d) `repo_dir`/build semantics** — with `force_build:false` + a pre-pulled image, confirm the run skips the build and doesn't require `repo_dir` to be populated (only its existence). If it DOES need the repo, point `repo_dir` at the extracted repo.
- [ ] **(e) harness importable** via `sys.executable -m multi_swe_bench.harness.run_evaluation` (i.e. `pip install -e` landed in the venv) and it writes `final_report.json` to `output_dir`.

---

## Self-review

**Spec coverage:** §4 firewall preserved (gold `fix_patch` + hidden `test_patch`/`f2p_tests` oracle-only; prompt issue-only from title/body/resolved_issues; Task 1). §5 isolation via the official image (materialize docker-cp; Task 2) — egress-lock still Plan 5. §7 dual-grading LIVE: official verdict (Task 3) + abench methodology v1 (Task 4), both real. §9 Phase-1 success = Task 5 end-to-end + spot-check. §10 open questions RESOLVED by the spike (recorded in ground-truth + memory).

**Placeholder scan:** Tasks 1,3,4 have exact pure-Python code + mocked seams (`_msb.run_evaluation`, `_docker_cp_repo`, `read_instance_report` — named, isolated, unit-tested with mocks). Task 2's docker-cp + Task 5's host steps are the genuine Docker-execution parts. `_run_abench_verify` v1 is a real subset (reads the harness report); the Joern blast-radius scoping is an explicitly-deferred enhancement, not a placeholder.

**Rework risk:** Task 1 rewrites merged `load`/`oracle`/`_image_ref`/`_build_prompt` (native schema) — the split-diff firewall and dual-grade assembly are UNCHANGED, so the leak-fix + dual-grade tests from Plan 4 core still apply. `_as_list` is dropped (native f2p are dicts) — remove its test.

**Type/name consistency:** `_msb.{instance_id,display_repo,base_sha,image_ref,issue_text,prediction_record,run_evaluation,read_instance_report,_docker_cp_repo}`, `oracle={record,base_sha,fix_patch,test_patch,f2p_tests,msb_root}`, `GradeResult(resolved, evaluator, standard_protocol, official_report, abench)` — used identically across tasks. `SweBenchAdapter.{load,materialize,grade}` matches the `BenchmarkAdapter` protocol + `run_benchmark`.
