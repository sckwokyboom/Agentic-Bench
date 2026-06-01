# Verify diagnostics (Phase 1) — design spec

**Date:** 2026-06-01
**Status:** approved (brainstorm)
**Builds on:** the existing verify subsystem (`abench/verify.py`, `abench/verify_parsers.py`,
`abench/runner.py`) and the Web UI (`abench_ui/`, `web/`).

## Problem

Every run's `verify_status` comes back `error`, for reasons the user can't see:

- `verify_status="error"` is a **catch-all** for five distinct causes in
  `verify.run_verify` — build/compile failure (`returncode != 0 && failed == 0`),
  test tool not on PATH, no parser for the command, parser `ValueError`, and the
  separate timeout path. Nothing records *which*.
- The captured `raw_output` (truncated to 8000 chars in `VerifyResult`) is
  **discarded by the runner** — it is never written to disk. So the operator has no
  log to read. `VerdictBanner.tsx` literally tells the user to "see
  verify_output.log", a file that is never created.
- There is no surfaced signal for whether the project even builds, nor which build
  system was detected. The user isn't sure the project compiled at all.

## Goals (Phase 1 — diagnostics)

Make a failed verify *explain itself*: a short reason + statistics, a readable
`verify_output.log` reachable from the UI, the detected build system shown, and a
loud warning when the untouched reference project itself fails verify (so the user
knows the problem is the command/environment, not the agent).

## Non-goals (deferred to Phase 2)

- Two-phase build-then-test separation (a distinct "builds ✓/✗" probe).
- UI-editable build-system/command override field.
- Injecting the verify command + "ensure it builds and tests pass" into agent prompts.

(These were chosen in brainstorming for Phase 2; Phase 1 keeps a single test command
and *classifies* its failure.)

## Approach

Additive: keep the `verify_status` contract `{passed, failed, skipped, error, timeout}`
unchanged (so `VerifyChip`, `VerifyStatusChip`, `report`, `metrics.success` need no
churn), and add a `reason` category + a one-line `message` alongside it, plus persist
the full output to a log. `error` now always carries a `reason` saying which kind.

## Data model (additive)

- `abench/verify.py` `VerifyResult` gains:
  - `reason: str` — one of: `passed`, `tests_failed`, `build_failed`,
    `tool_not_found`, `no_tests`, `timeout`, `unparseable`, `skipped`.
  - `message: str` — one-line human summary (e.g. "3 of 37 tests failed",
    "compilation failed before tests ran", "`mvn` not found on PATH").
  - `raw_output` becomes the **full** combined stdout+stderr (drop the 8000-char
    truncation; the log file needs the whole thing).
- `abench/trace_model.py` `Trace` gains `verify_reason: str | None` and
  `verify_message: str | None`. (`verify_status` unchanged. `raw_output` is NOT
  stored on the trace — it goes to the log file only, to keep `trace.json` small.)
- `abench/metrics.py` `extract` propagates `verify_reason` + `verify_message` into
  `metrics.json` (next to the existing `verify_*` keys). `success` logic unchanged.
- Frontend `web/src/api/types.ts`: add `verify_reason?: string | null` and
  `verify_message?: string | null` to `Trace` and `MetricsJson`.

## Classification (in `run_verify`)

Map `(exit code, parser result, output markers)` → `(status, reason, message)`:

| Condition | status | reason | message |
|---|---|---|---|
| `TimeoutExpired` | `timeout` | `timeout` | "verify timed out after {timeout_s}s" |
| no command detected (runner) | `skipped` | `skipped` | "no build system detected" |
| exit 127, or stderr matches `command not found` / `not found` for the tool | `error` | `tool_not_found` | "`{tool}` not found on PATH" |
| parser → `failed > 0` | `failed` | `tests_failed` | "{failed} of {passed+failed} tests failed" |
| parser → `run > 0, failed == 0`, exit 0 | `passed` | `passed` | "{passed} tests passed" |
| parser → `run == 0` (built, ran nothing) | `error` | `no_tests` | "no tests were run" |
| exit ≠ 0 and parser raised / no summary | `error` | `build_failed` | from markers (see below) |
| exit 0 but parser raised / no parser | `error` | `unparseable` | "could not parse test output" |

**`build_failed` message extraction** (best-effort, always falls back): scan
`raw_output` for the first of these markers and use a trimmed line —
`BUILD FAILURE`, `COMPILATION ERROR`, `error:` (javac), `cannot find symbol`,
gradle `FAILURE: Build failed` / `> Task :…FAILED`, pytest `errors during collection`
/ `collected 0 items`. Fallback: "build/command failed before tests ran (exit {code})".

`_parser_for(command) is None` (no parser, e.g. a custom `bash run.sh`): treat as
`unparseable` if exit 0, else `build_failed` — i.e. fold the old "no parser → error"
into the classification rather than a bare error.

The `(tool, first-token)` for messages comes from `command.split()[0]`.

## `verify_output.log`

- `run_verify` returns the full `raw_output`.
- The runner (`_run_one`) writes `rundir/verify_output.log` whenever verify ran,
  with a small header then the raw output:
  ```
  # command: mvn test
  # exit/status: error (build_failed)
  # duration: 51.3s
  ───
  <full stdout+stderr>
  ```
- The baseline pre-verify (`_maybe_run_baseline_verify`) writes
  `<experiment_dir>/.verify-baseline-output.log` and stores `reason`/`message` in the
  existing `.verify-baseline.json` cache, so a failing reference is diagnosable too.

## API

- `GET /api/runs/{name}/{condition}/{rep}/verify_log` → `text/plain` (reuses
  `runs.read_artefact(..., "verify_output.log")`); 404 if absent. Mirrors the existing
  `/patch` and `/events` routes.
- `GET /api/experiments/{name}/verify_command` → `{ "command": str | null,
  "system": "maven" | "gradle" | "pytest" | null }`. Runs `verify.detect_command` on
  the experiment's resolved `fixture_path` (honoring an explicit `verify.command`
  override if set — then `system` is derived from its first token, or `null`/"custom").
  Lets the UI show the detected build system *before* a run. 404 if experiment absent.

## UI

- **`VerifyCard`** (`web/src/components/VerifyCard.tsx`): headline becomes the
  `verify_message` (falling back to status), with the `reason` as a small label/chip;
  keep the pass/fail counts when present. Add a **"View verify output"** button that
  fetches `/verify_log` and shows it in a dialog or inline collapse (monospace,
  `selectable`, dark terminal styling consistent with EventStream). Show the detected
  build system + command, derived from `verify_command` (mvn/mvnw → Maven, gradle/
  gradlew → Gradle, pytest → pytest, else → custom).
- **`VerdictBanner`** (`web/src/components/VerdictBanner.tsx`): the `error` branch
  shows `verify_message` and points to the now-real log (the VerifyCard button).
- **Baseline warning:** when `trace.verify_baseline_unknown` is true, render a
  prominent warning on TraceView ("The reference project itself does not pass verify —
  build/environment issue; run verdicts may be unreliable.") and a small chip on the
  ExperimentResults page.
- **ExperimentEdit Fixtures panel** (`web/src/components/FixturesPanel.tsx` or its
  host): show the detected build system from `GET /api/experiments/{name}/verify_command`
  — "Build system: Maven · `mvn test`", or "No build system detected — set
  `verify.command`" when null.
- New hook `useVerifyLog(name, condition, rep)` (lazy/enabled-on-open) and
  `useDetectedVerify(name)`; new `RunSummary`/types unaffected.

## Testing

- **Python (`tests/`):** table-driven unit tests for the classifier — one per reason
  (`tool_not_found` via exit 127 / "command not found"; `build_failed` via maven
  "BUILD FAILURE" with no test summary; `tests_failed` with counts; `passed`;
  `no_tests` via run==0; `unparseable`; `timeout`). Each asserts `(status, reason,
  message-substring)`. A runner test asserting `verify_output.log` is written with the
  header + body, and that `.verify-baseline-output.log` is written. Endpoint tests for
  `/verify_log` (200 + 404) and `/experiments/{name}/verify_command` (detect + null).
- **Frontend (`web/tests/`):** `VerifyCard` renders the message/reason + the
  "View verify output" button (MSW-mock the log endpoint, assert the log text appears
  on click); build-system label derivation; baseline-warning render when
  `verify_baseline_unknown`.

## Risks / notes

- With `shell=True`, a missing tool yields exit 127 from the shell (not a Python
  `FileNotFoundError`), so `tool_not_found` is detected from the exit code / "command
  not found" marker, not the `FileNotFoundError` path (which stays as a fallback).
- Don't bloat `trace.json`: full output lives only in `verify_output.log`; the trace
  keeps the short `verify_message`.
- The detected-build-system endpoint reads the fixture dir; if `fixture_path` isn't
  populated yet, `detect_command` returns null → UI shows the "not detected" hint
  (this is itself a useful signal).
- `metrics.success` semantics are unchanged: `build_failed`/`no_tests`/`tool_not_found`
  all keep `verify_status="error"` → `success=None` (not a test failure). The new
  `reason` only adds explanation, not a verdict change.
