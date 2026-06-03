# Diff/Verify Validity + Per-Run Logging + Service-Error Surfacing — Plan

> Use superpowers:subagent-driven-development. TDD; never weaken tests.

**Why:** A real run showed the "final diff" was just `opencode.json` and all 6 reps scored an identical 42/42. Root causes (code-verified):
1. `abench/opencode_client.py:145` writes `opencode.json` INTO the workdir; `abench/fixture.py:diff_workdir` does `git add -A; git diff --cached HEAD`, so opencode's own config pollutes the diff. The agent made NO source edits (proxy/model errors → no-op), so the diff shows only `opencode.json`.
2. Verify DOES run on the per-run workdir after the agent (`runner.py:170`), but since the code never changed, results are identical. Worse, if the STRIPPED fixture already passes the same tests as the reference, verify can't distinguish agent work at all — and nothing warns about it (the current baseline check runs on `reference_path` only and only flags when the reference FAILS).
3. Model/proxy errors go to process stderr (`opencode_client.py:206`) — never persisted to a file, never counted.

**User decisions:** per-run `run.log` + error counters; warn loudly on insensitive-verify / no-op (don't block).

---

## Task A — Backend mechanics (the core)
**Files:** `abench/fixture.py`, `abench/opencode_client.py`, `abench/runner.py`, `abench/trace_model.py`, `abench/metrics.py`, `abench/report.py`; tests.

### A1. Exclude opencode artifacts from the diff
- In `abench/fixture.py`, define `OPENCODE_ARTIFACTS = ("opencode.json", ".opencode")`. Change `diff_workdir` to `git diff --cached HEAD -- . :(exclude)opencode.json :(exclude).opencode :(exclude).opencode/**` (pass each as a separate pathspec arg). `git add -A` still stages everything (harmless); the diff just omits the artifacts. Result: `changes.patch`/`final_diff_summary` show only real source changes.
- Add `made_source_changes: bool` derivation: `bool(diff_workdir(...).strip())`.
- Test (`tests/test_fixture.py` or new): create a workdir, add a real source file change AND write an `opencode.json` + a `.opencode/x` file → `diff_workdir` includes the source change, EXCLUDES `opencode.json` and `.opencode/*`. And: no source change + only opencode.json → empty diff.

### A2. Per-run log file + service-error counters
- `RealOpenCodeClient.run_task` + the `OpenCodeClient` Protocol gain an optional `log_sink: Callable[[str], None] | None = None`. Route the stderr-drain lines AND the harness `_log` lines for this run into `log_sink` (in addition to stderr). Count, while processing `raw_events` + stderr:
  - `n_service_errors`: count of error events (`ev.get("type")=="error"` or `part.type=="error"`) — i.e. model/provider/proxy failures surfaced by opencode.
  - `n_rate_limits`: subset whose status/code is 429 (reuse the existing 429 detection).
  - Capture up to ~5 `service_error_messages` (short strings) for display.
  Put these on the `Trace` (new fields `n_service_errors:int=0`, `n_rate_limits:int=0`, `service_error_messages:list[str]=[]`). Keep the existing `interrupted_reason` logic.
- `runner._run_one`: open `rundir/"run.log"` and pass a `log_sink` that writes to it (so the file captures the full opencode stderr + key harness lines for THIS run). Close it in `finally`. Also write a short header (condition/rep/model/command).
- `metrics.extract`: emit `n_service_errors`, `n_rate_limits`, `made_source_changes` (compute `made_source_changes` from the patch passed in: non-empty after exclusion). Add the three keys.
- `report.NUMERIC`: add `n_service_errors`, `n_rate_limits` (numeric, neutral). `made_source_changes` is boolean — not in NUMERIC.
- Tests: a fake client that emits an error event (429 + a 503) → trace has `n_service_errors>=2`, `n_rate_limits==1`; `_run_one` writes a non-empty `run.log`; metrics carry the counters + `made_source_changes` reflects the patch.

### A3. Baseline sensitivity (stripped fixture vs reference)
- Extend the pre-flight baseline: in addition to verifying `reference_path` (current), verify the STRIPPED `fixture_path` too (fresh workdir each, best-effort, cached by sha). Store in `.verify-baseline.json`: `{reference_sha, reference_status, fixture_sha, fixture_status}`.
- Define `verify_insensitive = (fixture_status == "passed")` — the stripped fixture already passes the tests the runner runs, so verify cannot distinguish agent work. Propagate to each run's trace: new field `verify_insensitive: bool = False` (set from the cache in `_run_one`, like `verify_baseline_unknown`). Keep `verify_baseline_unknown` (reference failed/unknown) as-is.
- Tests: with a fixture that passes baseline → `verify_insensitive` True propagated to runs; with a fixture that fails baseline → False. (Use stub verify via a trivial command; or monkeypatch run_verify.)

Commit A when green.

## Task B — Server: expose log + flow new fields through endpoints/envelopes
**Files:** `abench_ui/runs.py`, `abench_ui/server.py`, `abench_ui/run_session.py`; tests.
- `read_artefact` already serves files by name → add `run.log` to the allowed artefacts (or a dedicated `GET /runs/{name}/{condition}/{rep}/run_log?batch=` returning text). Confirm `list_runs` summary surfaces `n_service_errors`/`interrupted_reason`/`made_source_changes` (it reads metrics.json; add these keys to whatever subset it returns).
- `run.finished` envelope: add `n_service_errors`, `made_source_changes`, and pass through `verify_insensitive` if available, so the live page can show errors per run.
- Tests: the run_log endpoint returns the file (404 if absent); list_runs includes the new fields; envelope carries them.

## Task C — Frontend: surface errors, cleaned diff, sensitivity, log viewer
**Files:** `web/src/api/types.ts`, `queries.ts`, `ws/envelope.ts`, `components/FinalDiffCard.tsx`, `components/VerdictBanner.tsx` (or a new banner), `components/ProgressHeader.tsx`, `components/RunsTable.tsx`, `pages/TraceView.tsx`, `pages/Run.tsx`, a new `RunLogViewer`/reuse RawEventsToggle pattern; tests.
- Types: `MetricsJson`/`RunSummary` gain `n_service_errors?`, `n_rate_limits?`, `made_source_changes?`, `verify_insensitive?`; envelopes gain `n_service_errors?`, `made_source_changes?`.
- **Service errors**: ProgressHeader shows a red "N errors" chip (with `WarningAmber`/`ErrorOutline`) when `n_service_errors>0`; RunsTable adds an errors indicator; TraceView shows a banner "N service/proxy errors during this run — see run log" when >0 or `interrupted_reason` set.
- **Cleaned diff + no-op**: FinalDiffCard already renders the patch/summary (now clean). When `made_source_changes === false` (or empty diff), show a prominent "No source changes — the agent did not edit any files" warning instead of an empty diff.
- **Verify insensitivity**: TraceView + ExperimentResults show a warning banner when `verify_insensitive` — "Verify cannot distinguish agent work: the stripped fixture already passes these tests. Pass/fail counts are not meaningful for this task."
- **Run log viewer**: in TraceView, a collapsible "Run log" (dark terminal, like RawEventsToggle) fetching `run_log` via a new `useRunLog(name,cond,rep,batch)` hook.
- Tests: error chip/banner render when counts>0; FinalDiffCard "no source changes" state; insensitivity banner; run-log hook requests the right URL.

## Task D — Integration + live smoke + review
- Frontend suite + tsc + build; Python suite (minus 2 env e2e).
- Boot smoke: seed a run with `made_source_changes=false` + `n_service_errors=3` + `verify_insensitive=true` → confirm: FinalDiff shows "no source changes", error chip/banner shows "3 errors", insensitivity banner shows, run.log viewer opens. Seed a normal run with a real `.java` diff → diff shows the code (no opencode.json). Screenshot.
- Final cross-cutting review (esp. that diff exclusion can't hide real changes, error counting is accurate, sensitivity logic correct).

## Self-review notes
- The diff exclusion must NOT hide real source files that happen to live under an excluded path (only `opencode.json` + `.opencode/` are excluded — both are opencode's own).
- `verify_insensitive` is the honest signal that 42/42 is meaningless; combined with `made_source_changes=false` it explains the identical-results symptom end to end.
- Per-run `run.log` is the analyzable artifact for "how many proxy errors"; counters make it queryable without parsing.
