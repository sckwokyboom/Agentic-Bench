# SWE-bench-java pilot — first-run runbook (jackson-core)

The `swebench-java` adapter code is done, reviewed, and merged. This runbook covers
the host prerequisites (Docker + a model + the official image) needed for the first
real run. Ground truth: the official harness is
`github.com/multi-swe-bench/multi-swe-bench` **pinned @ `24f493f8` (v1.1.0)**.

## Linux / WSL (the box the pilot actually runs on) — start here
The macOS case-sensitivity blocker below **does not apply**: ext4 is case-sensitive, so
the harness clones and imports normally. Use [`experiment-deepseek.yaml`](./experiment-deepseek.yaml).

```bash
# 1. Docker (WSL2: Docker Desktop with WSL integration, or dockerd inside the distro)
docker version                      # Server section must be present

# 2. Harness, pinned, in its OWN python env (deps must not land in abench's venv)
git clone https://github.com/multi-swe-bench/multi-swe-bench.git ~/multi-swe-bench
cd ~/multi-swe-bench && git checkout 24f493f8a103e72312ded4f6b9c89f081d69cb09
python3.11 -m venv .venv && .venv/bin/python -m pip install -e .
.venv/bin/python -c "import multi_swe_bench.harness.run_evaluation; print('ok')"   # must print ok

# 3. Dataset (native ByteDance Multi-SWE-bench records — NOT the flat HF schema)
mkdir -p ~/msb-data      # put jackson-core.jsonl here, then trim to one instance:
head -1 ~/msb-data/jackson-core.jsonl > ~/msb-data/jackson-one.jsonl

# 4. Pre-pull the images for the instance you run (the harness does NOT auto-pull;
#    absent images are rebuilt from scratch, which is very slow)
python3 -c "import json,sys; r=json.loads(open('$HOME/msb-data/jackson-one.jsonl').readline()); \
print(f\"mswebench/{r['org']}_m_{r['repo']}:pr-{r['number']}\")"    # exact tag to pull
docker pull mswebench/fasterxml_m_jackson-core:base
docker pull mswebench/nix_swe:v1.0

# 5. Point experiment-deepseek.yaml's msb_root/msb_python/dataset at your paths, then
export DEEPSEEK_API_KEY=…
cd experiments/swebench-java && abench run experiment-deepseek.yaml
```

**Validate the grade path FIRST, without a model** (runbook step 7 below): feed the
dataset's own `fix_patch` as the candidate diff — `official.resolved` MUST be `true`.
If that fails, nothing downstream is trustworthy and no agent run is worth its cost.

**Orchestration (rcc) is NOT available in benchmark mode yet.** bench/run.py calls the
agent directly, so an orchestrated condition would run baseline under an `rcc` label;
config validation now REFUSES that instead of mis-labelling it. Wiring orchestration
into benchmark mode (it needs a per-instance suite runner — maven/gradle per repo) is
the prerequisite for any rcc-vs-baseline A/B here.

## ⚠️ macOS blocker found during prep — case-sensitive FS required for the harness
The harness ships two dirs differing only in case (`multi_swe_bench/harness/repos/python/Qiskit/`
and `.../qiskit/`). On a default **case-INSENSITIVE** macOS APFS they collide, git merges them,
and `python -m multi_swe_bench.harness.run_evaluation` **fails to import** (`ModuleNotFoundError:
...repos.python.qiskit`) — even `--help` crashes, regardless of target language (the package eagerly
imports all repos). The `~/Projects/multi-swe-bench` checkout made during prep is on the default
(case-insensitive) volume and is therefore import-broken. **Fix: put the harness on a case-sensitive
volume.** macOS APFS lets you add one without repartitioning:
```bash
diskutil apfs listVolumes                         # find your APFS container (e.g. disk3)
diskutil apfs addVolume disk3 "Case-sensitive APFS" MSB    # mounts at /Volumes/MSB
cd /Volumes/MSB && git clone https://github.com/multi-swe-bench/multi-swe-bench.git
cd multi-swe-bench && git checkout 24f493f8a103e72312ded4f6b9c89f081d69cb09
python3.11 -m venv .venv && .venv/bin/python -m pip install -e .
.venv/bin/python -c "import multi_swe_bench.harness.run_evaluation; print('ok')"   # must print ok
```
Then set `experiment-pilot.yaml` `subset.msb_root: /Volumes/MSB/multi-swe-bench` and
`subset.msb_python: /Volumes/MSB/multi-swe-bench/.venv/bin/python`. (Alternative: run the harness
entirely inside a Linux container — heavier; the case-sensitive volume is simplest.)

## Already prepared (by the assistant)
- ✅ Harness cloned + pinned: `~/Projects/multi-swe-bench` @ `24f493f8` — **but import-broken on the
  default case-insensitive FS (see the blocker above); re-clone onto a case-sensitive volume).** The
  editable install + `python3.11` venv approach itself works (verified `pip install -e` succeeds).
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

### 2. Set up the harness on a case-sensitive volume + its own python env
See the ⚠️ blocker above — do the case-sensitive-volume clone + `python3.11 -m venv .venv` +
`pip install -e .` there, and confirm the `import ... run_evaluation; print('ok')` sanity check
prints `ok`. Use **python3.11** (this host's `python3.12` venv/pip was broken during prep); the
harness deps (docker/swe-rex/PyGithub/gitpython) must NOT go into abench's 3.14 venv. Update
`experiment-pilot.yaml`'s `subset.msb_root`/`subset.msb_python` to the case-sensitive-volume paths.

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
