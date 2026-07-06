# SWE-bench-java pilot — first-run runbook (jackson-core)

The `swebench-java` adapter code is done, reviewed, and merged. This runbook covers
the host prerequisites (Docker + a model + the official image) needed for the first
real run. Ground truth: the official harness is
`github.com/multi-swe-bench/multi-swe-bench` **pinned @ `24f493f8` (v1.1.0)**.

## Already prepared (by the assistant)
- ✅ Harness cloned + pinned: `~/Projects/multi-swe-bench` @ `24f493f8`.
- ✅ Native jackson-core dataset downloaded + **schema-validated against `_msb`**:
  `~/Projects/msb-data/jackson-core.jsonl` (18 instances). All adapter accessors
  (`org`/`repo`/`number`/`base.sha`/`f2p_tests`/`title`/`resolved_issues`/`fix_patch`/
  `test_patch`) match the real records; the gold-derived `hints` field is present and
  is firewalled off (never shown to the agent).
- ✅ Pilot experiment config: [`experiment-pilot.yaml`](./experiment-pilot.yaml) + [`system.md`](./system.md).
- ✅ Code supports a configurable harness interpreter via `subset.msb_python`.

## Steps for you

### 1. Install + start Docker Desktop (macOS)
`brew install --cask docker` then launch Docker.app (or install from docker.com).
Confirm: `docker version` shows a running Server. (Note: this host's `python3.12`
venv was broken during prep — use a working Python for step 2.)

### 2. Install the harness into its OWN python env
The harness deps (docker, swe-rex, PyGithub, gitpython, …) should NOT go into abench's
3.14 venv. Use a working Python ≥3.10:
```bash
cd ~/Projects/multi-swe-bench
python3.11 -m venv .venv          # or any working ≥3.10 python
.venv/bin/python -m pip install -e .
# sanity: the module is importable
.venv/bin/python -c "import multi_swe_bench.harness.run_evaluation; print('ok')"
```
`experiment-pilot.yaml`'s `subset.msb_python` already points at `~/Projects/multi-swe-bench/.venv/bin/python`.

### 3. Pre-pull the pilot Docker image (offline determinism)
The harness does NOT auto-pull; it checks locally then builds from scratch if absent.
Pre-pull so grading runs offline:
```bash
cd ~/Projects/multi-swe-bench
# All verified images (large) — OR just the jackson-core ones you need:
docker pull mswebench/fasterxml_m_jackson-core:base
docker pull mswebench/fasterxml_m_jackson-core:pr-1309     # (and other pr-<N> you run)
docker pull mswebench/nix_swe:v1.0                         # helper container the harness ensures
# grep scripts/images_verified.txt for the full jackson-core tag list (19 tags).
```

### 4. Point the config at your model
Edit [`experiment-pilot.yaml`](./experiment-pilot.yaml): set `model:` and the
`opencode.providers[]` block (base_url / models / api_key_env) to your provider
(hosted API or local vLLM). Export the API-key env var.

### 5. First run — start with ONE instance
For the very first run, trim the dataset to a single line to keep it fast:
```bash
head -1 ~/Projects/msb-data/jackson-core.jsonl > ~/Projects/msb-data/jackson-one.jsonl
# point experiment-pilot.yaml `dataset:` at jackson-one.jsonl, then:
cd ~/Projects/Agentic-Bench/experiments/swebench-java
# run via your usual abench entrypoint (CLI or web UI), e.g.:
#   <abench run command> experiment-pilot.yaml
```
Artifacts land in `experiments/swebench-java/runs/<instance>/baseline/rep_0/`
(`grade.json`, `trace.json`, `changes.patch`, `metrics.json`) + `benchmark_summary.json`.

### 6. MUST-CONFIRM on the first run (from the opus review — these can SILENTLY mis-grade, not crash)
Spot-check, don't just trust a green run:
- **(a) `abench["report_found"]` is `true`** in `grade.json`. If `false`, the harness
  wrote its per-instance `report.json` somewhere other than `workdir` → `_msb.find_instance_report`'s
  glob root needs fixing, and the whole abench-methodology plane (regressions/repro)
  is silently zeroed until then. The official `resolved` is unaffected.
- **(b) `official.resolved` matches a manual spot-check** — run the harness by hand on
  the SAME `{org,repo,number,fix_patch}` prediction and confirm the `resolved_ids`
  verdict agrees. Confirm the `resolved_ids` id string is exactly `fasterxml/jackson-core:pr-<N>`
  (case-sensitive join). jackson is all-lowercase, so the pilot is safe; re-check before
  scaling to mixed-case repos (jib=`GoogleContainerTools`).
- **(c) `repo_dir`/build**: with `force_build:false` + a pre-pulled image, confirm the
  run skips building (doesn't need `repo_dir` populated). If it insists on building,
  the image tag didn't match — recheck step 3.

### 7. Sanity option — grade the GOLD patch (no model needed)
To validate the grade path in isolation before wiring a model: feed the dataset's own
`fix_patch` as the "agent" diff → `official.resolved` MUST be `true`. (A quick script
that calls `SweBenchAdapter.grade` with the gold `fix_patch`, or a one-off prediction
JSONL through the harness directly.)

## After the pilot
Record the confirmed facts (real image tags, `resolved_ids` format, report.json location,
timing) back into `docs/superpowers/plans/2026-07-06-bench-layer-phase4b-*.md` Task 5 +
memory `multi-swe-bench-evaluator-interface`. Then scale to the other jackson-core
instances, then the other Java repos. Egress-lock (agent-container network isolation)
is **Plan 5** — the pilot runs without it (the agent container is not yet egress-locked).
