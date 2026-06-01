# Re-verify — design spec

**Date:** 2026-06-01
**Status:** approved (brainstorm)
**Builds on:** verify diagnostics Phase 1 (`abench/verify.py` classifier, `verify_output.log`,
`verify_reason`/`verify_message`), `abench/runner.py`, `abench/fixture.py`, `abench_ui/`.

## Problem

Verify diagnostics are produced only at run time. Existing runs predate the feature
(no `verify_reason`/`verify_message`, no `verify_output.log` on disk), so the UI shows
nothing new for them. The only way to populate diagnostics today is a full `abench run`,
which **re-runs the agent** — expensive, non-deterministic, and unnecessary when the user
only wants to confirm "does this run's result build, and do its tests pass / how many /
which?".

## Goal

Re-run **only the verify step** against an existing run's saved result — without invoking
the agent — and write the (classified) diagnostics back into that run's artefacts. This
retroactively lights up old runs and gives an on-demand "build + tests" check that costs
no LLM tokens and is deterministic.

## Feasibility (confirmed)

Each run persisted `changes.patch` (`runner.py:153`, `git diff` vs the fixture seed commit)
and the experiment's `fixture_path` is on disk. So a run's working tree can be
reconstructed: `fixture.create_workdir(fixture_path)` (fresh copy at the seed commit) →
`git apply changes.patch` → run the classified `verify.run_verify`. No agent involved.

## Approach

A pure core (`abench/reverify.py`) reused by three surfaces: a `abench verify` CLI command,
a background-task API (`POST /api/verify` + a polling `GET /api/verify/{id}` status), and UI
"Re-verify" buttons. UI progress uses **polling** (the existing `useSessionState`/
`refetchInterval` pattern), NOT the WebSocket run-session machinery — re-verify progress is
coarse (per-run, seconds-to-minutes), so polling is sufficient and far lighter.

## Core — `abench/reverify.py`

```
reverify_run(exp: Experiment, condition: str, rep: int) -> VerifyResult
```
1. `rundir = exp.output_dir / exp.name / condition / f"rep_{rep}"` (same layout the runner
   writes; confirm against `runner._run_one`). If `rundir` or `rundir/changes.patch` is
   absent → `VerifyResult(status="error", reason="no_run", message="no saved run at <cond>/rep_N")`.
2. `workdir, _sha = fixture.create_workdir(exp.fixture_path)`; then
   `git apply` the run's `changes.patch` inside `workdir`.
   - If `git apply` exits non-zero → cleanup, return
     `VerifyResult(status="error", reason="patch_apply_failed",
     message="could not reconstruct workdir: changes.patch did not apply (fixture changed?)",
     command=None)`.
3. `command = exp.verify.command or verify.detect_command(workdir)`; if None →
   `VerifyResult(status="skipped", reason="skipped", message="no build system detected")`.
4. `v = verify.run_verify(workdir, command, exp.verify.timeout_s)` (the Phase-1 classifier).
5. **Write back** into `rundir` (overwrite in place):
   - `trace.json`: load, set `verify_status/command/duration_s/passed_count/failed_count/
     failed_names/reason/message`, write.
   - `metrics.json`: load, set the same `verify_*` keys + recompute `success` via the shared
     rule (passed→True, failed→False, else None).
   - `verify_output.log`: written via `runner._write_verify_log(rundir, v)` (reuse the
     Phase-1 helper so the header format stays single-sourced).
   - `fixture.cleanup(workdir)` in a `finally`.
6. Return `v`.

```
reverify_experiment(exp: Experiment) -> Iterator[tuple[str, int, VerifyResult]]
```
Walk the existing run dirs under `exp.output_dir / exp.name` (`*/rep_*` with a
`changes.patch`), yielding `(condition, rep, reverify_run(...))` per run. Re-verify runs even
when `exp.verify.enabled` is false — it is an explicit user request.

**Shared success rule:** extract the metrics success derivation into a tiny helper
`metrics._success_from_status(status) -> bool | None` and use it in both `metrics.extract`
and `reverify_run`, so they cannot drift.

## CLI — `abench verify`

`abench verify <experiment.yaml> [--condition C --rep N]`:
- No `--condition/--rep` → `reverify_experiment` over all saved runs.
- Both given → single `reverify_run`.
- Prints one line per run: `baseline/rep_0 → passed (37/37)`, `baseline/rep_1 → error/build_failed`.
- Synchronous (terminal; no HTTP-timeout concern). Exit 0 always (it's a diagnostic, not a gate).

## API — background task + polling status

- In-memory registry `_verify_jobs: dict[str, dict]` in `server.py` (module/app state), each:
  `{state: "running"|"done"|"error", total, done, current: {condition,rep}|None,
  results: [{condition, rep, status, reason, message, passed_count, failed_count}], error: str|None}`.
- `POST /api/verify` body `{name: str, condition?: str, rep?: int}` → `{verify_id}`
  (`verify_id = uuid4().hex`). Resolves the experiment
  (`load_experiment(_exp_dir_for(name)/"experiment.yaml")`), seeds the job dict, and schedules
  the work via `asyncio.create_task(...)` where the task body does
  `await loop.run_in_executor(None, _run_reverify_job, ...)` — the blocking re-verify loop runs
  in a threadpool so the POST returns immediately and the event loop stays responsive. The job
  function iterates the target set (single or whole experiment), updating the job dict after
  each run (`done`, `current`, append to `results`), then sets `state="done"` (or
  `state="error"` + `error` on an unexpected exception).
- `GET /api/verify/{verify_id}` → the job dict (404 if unknown).
- 404 when the experiment/run is absent; a per-run failure (patch/no_run) is recorded as a
  result entry, not a job-level error (the job still completes).

## UI

- **`useStartReverify()`** mutation → `POST /api/verify`; **`useReverifyStatus(verifyId)`**
  query with `refetchInterval` while `state === "running"` (mirrors `useSessionState`).
- **VerifyCard:** a "Re-verify" button (next to "View verify output") → starts a single-run
  re-verify (`{name, condition, rep}`), shows an inline spinner/progress while running, and on
  `done` invalidates `qk.trace` + `qk.metrics` + `qk.verifyLog` for that run so the card
  refreshes with the new diagnostics.
- **ExperimentResults:** a "Re-verify all" button → whole-experiment re-verify, shows
  `done/total` progress, and on completion invalidates `qk.runs` + `qk.runsSummary` (+ trace
  queries) so the table/summary refresh.
- Buttons disabled while a job for that target is running.

## Testing

- **Core (`tests/`):** `reverify_run` happy path (patch applies → `run_verify` mocked →
  trace.json + metrics.json updated with verify_* and recomputed `success` + verify_output.log
  written); `patch_apply_failed` (malformed patch → that reason, no write of bogus success);
  `no_run` (missing rundir); overwrite of an OLD run dir that had no verify_* fields;
  `reverify_experiment` yields all runs. Use a tiny real fixture + a real `git apply` for the
  happy/patch-fail paths (deterministic, no network).
- **CLI:** `abench verify` single + all (print format + writes back).
- **API:** `POST /api/verify` → verify_id; `GET /api/verify/{id}` reaches `done` with results;
  unknown id → 404; per-run patch failure surfaces as a result entry. Mock/stub `run_verify`
  (or use a fixture that builds trivially) to keep tests fast.
- **Frontend:** Re-verify button starts the job, polls, and invalidates queries on done
  (MSW-mock `POST /api/verify` + the status endpoint).

## Risks / notes

- `run_verify` is blocking (subprocess build); the API must run it off the event loop
  (`run_in_executor`/threadpool) so the server stays responsive.
- Re-verify reconstructs the build environment each call; for Maven the first build may fetch
  dependencies (slow, network). That's inherent to verifying; the per-run `verify.timeout_s`
  bounds it.
- Overwrite is in place and intentional — re-verify is the source of truth for diagnostics on
  an existing run. (No append/side-file.)
- This is still within verify diagnostics; two-phase build/test, the UI build-system override
  field, and prompt injection remain Phase 2.
