# Run Batches + Live-Run Fixes + UI Polish — Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development. TDD throughout; never weaken tests.

**Goal:** (1) Preserve every experiment execution as a timestamped *batch* instead of overwriting; (2) fix the live-run status bugs (duplicate-count, non-updating/non-clickable sidebar, fake isolation chip, broken verify badge); (3) clarify fixture/reference + nonce in the UI; (4) replace all emoji with MUI icons.

**User decisions:** timestamped batches (not archive/guard); do everything in one effort.

**Tech:** Python (pydantic v2, FastAPI, pathlib), React 18 + TS strict + `noUncheckedIndexedAccess`, MUI v5 + `@mui/icons-material`, TanStack Query, react-router-dom v6, Vitest.

---

## Design

### Run-batch storage
Today (OVERWRITES): `runner.py` writes `output_dir/<exp>/<cond>/rep_N/`; server reads `<exp_dir>/runs/<exp>/<cond>/rep_N`.
New layout: insert a **batch** segment → `output_dir/<exp>/<batch_id>/<cond>/rep_N/`.
- `batch_id` = UTC timestamp `YYYYMMDD-HHMMSS` (sortable, human-readable). Generated once per `run_experiment` invocation (CLI) / per `RunSession` (UI). If a caller passes an explicit `batch_id`, use it.
- **Back-compat (do NOT lose existing runs):** a legacy flat layout has condition dirs (e.g. `baseline/rep_0/metrics.json`) directly under `<exp>/`. The batch enumerator must surface this as a synthetic batch id `"legacy"` WITHOUT moving files; artefact reads for batch `"legacy"` map to the flat path. New runs always create timestamp batches.
- A batch dir is detected by containing `*/rep_*/metrics.json` (depth 2); legacy = `<exp>/<cond>/rep_*/metrics.json` (depth 2 from `<exp>`). Distinguish: if `<exp>` has children that are themselves cond dirs containing `rep_*` → legacy; if children contain `<cond>/rep_*` → batches.

### Endpoints (batch-aware, latest-by-default)
- `GET /api/runs/{name}/batches` → `[{id, started_at, total_runs, valid_runs, success_rate}]` sorted newest-first (synthesizes `"legacy"` if present).
- Existing endpoints gain an OPTIONAL batch, defaulting to the newest batch:
  - `GET /api/runs/{name}?batch=<id>` → runs of that batch (default newest).
  - `GET /api/runs/{name}/summary?batch=<id>`.
  - `GET /api/runs/{name}/{condition}/{rep}/<artefact>?batch=<id>` (trace/metrics/patch/events/verify_log) — default newest batch. Keep query-param form to avoid breaking the route shape; the SPA passes the batch it's viewing.
- `RunSession` includes `batch_id` in the `session.started` and `run.finished` envelopes so the live UI can deep-link to `/runs/<exp>/<cond>/<rep>?batch=<id>`.

### Live-run bug fixes
1. **Duplicate-count on reconnect** (`7 done/1 running` from 6): server `ws_buffer.replay_from` is inclusive (`eid >= last`) and client appends unconditionally. Fix BOTH: server → exclusive (`eid > last`); client `useRunSession.onmessage` → only append when `event_id > lastIdRef` (skip already-seen), still updating `lastIdRef`. Envelopes without numeric `event_id` always append (defensive). (Counter starts at 1, so first-connect `last=0` still yields everything.)
2. **Sidebar non-updating / non-clickable**: make `RunSidebar` cards clickable → navigate to `/runs/<exp>/<cond>/<rep>?batch=<batch_id>` for runs that are `done` (and allow opening a `running` run's partial trace if artefacts exist). Drive the sidebar from live envelopes AND a polling backstop: while the session is live, `useRuns(name, batch)` with `refetchInterval` so statuses update even if the socket hiccups. Thread `experimentName` + `batch_id` (from `session.started`) into the sidebar.
3. **Fake isolation chip**: `Run.tsx` hardcodes `{nonce:true,shuffle:true}`. Emit real `isolation: {nonce_prefix, shuffle_order}` in `session.started`; read it; render via `IsolationChip` with a **tooltip** ("nonce = unique comment prefixed to the system prompt so each run misses the provider prompt-cache; shuffle = randomized run order to avoid ordering bias").
4. **Verify badge "0/0"**: `VerifyChip` renders `passed/passed` and `ProgressHeader` hardcodes `status="passed"`. Fix to show `passed/total` with the real aggregate status (passed if no failures and ≥1 test, failed if any failure, else neutral). Only count runs that produced verify results.

### fixture/reference + nonce clarity
- `FixturesPanel`: under the fixture/reference rows add short captions: *fixture = working tree the agent edits (stripped project)*; *reference = ground-truth original for comparison*. (Tooltips or captions.)
- nonce: covered by the IsolationChip tooltip above; also the form field already has the pydantic description.

### Emoji → MUI icons (sweep)
Replace every emoji in `web/src/**` with `@mui/icons-material` (size="small", `fontSize="inherit"` where inline). Mapping:
- 💭 reasoning → `PsychologyOutlined`; 🗨 text → `ChatBubbleOutline`; 📝 edit → `EditNote`/`DescriptionOutlined`.
- ✓ success → `CheckCircle`/`CheckCircleOutline`; ✗ fail → `Cancel`/`HighlightOff`; ✎ pending → `PendingOutlined`/`HourglassEmpty`.
- ▶ run → `PlayArrow`; ▾ expand → `ExpandMore`; ⚠ warning → `WarningAmber`; 🧪 verify → `ScienceOutlined`.
- 🔒 isolation on → `Lock`; 🔓 off → `LockOpen`.
Files: `TurnCard.tsx`, `VerifyChip.tsx`, `VerifyCard.tsx`, `IsolationChip.tsx`, `RunsTable.tsx`, `VerdictBanner.tsx`, `RootObjectFieldTemplate.tsx`, `FixturesPanel.tsx`, `ModelValidationChip.tsx`, `SavedExperimentCard.tsx`, `ExperimentEdit.tsx`, `RawEventsToggle.tsx`, `MethodComparisonCard.tsx`. Update any tests that matched emoji text (assert on icon `data-testid` / `aria-label` / `getByTestId` instead). Keep the SAME semantic meaning; don't weaken tests — adapt matchers to the icon.

---

## Tasks

### Task 1 — Backend: batch storage in `runner.py`
**Files:** `abench/runner.py`, `abench/cli.py` (run subcommand), `tests/test_runner*.py` (or a new `tests/test_run_batches.py`).
- `run_experiment(exp, ..., batch_id: str | None = None)`: if None, `batch_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")`. Build `root = exp.output_dir / exp.name / batch_id`; per-run dir `root / cond.name / f"rep_{rep}"`. Return/expose the batch_id used.
- CLI `abench run`: generate one batch per invocation (or accept `--batch-id`); print it.
- Test: two `run_experiment` calls (mock the agent client) produce TWO distinct batch dirs, neither overwriting the other; artefacts land under `<exp>/<batch>/<cond>/rep_N`. (Use a fake/stub client + a passed explicit batch_id to make it deterministic — `Date.now`-style nondeterminism: pass explicit batch_ids in the test.)
- Keep all existing runner behavior (verify, trace.json, metrics.json) intact.

### Task 2 — Backend: batch-aware enumeration + endpoints + envelopes
**Files:** `abench_ui/runs.py`, `abench_ui/server.py`, `abench_ui/run_session.py`, `abench_ui/report.py` (if summary path-bound), `tests/abench_ui/test_runs_api.py`, `test_run_session.py`, new `test_batches.py`.
- `runs.py`: add `list_batches(exp_runs_dir)` (newest-first; synthesize `"legacy"` for a flat layout, no file moves) and make `list_runs`/`read_artefact`/summary accept a `batch` (default newest; map `"legacy"`→flat). Robust legacy detection per Design.
- `server.py`: add `GET /runs/{name}/batches`; add optional `?batch=` to `/runs/{name}`, `/runs/{name}/summary`, and the artefact endpoints; default to newest batch. 404 if batch missing.
- `run_session.py`: generate/accept `batch_id`, pass it to `run_experiment`, and include `batch_id` (+ real `isolation: {nonce_prefix, shuffle_order}`) in the `session.started` envelope and `batch_id` in `run.finished`.
- `ws_buffer.replay_from`: change `eid >= last_event_id` → `eid > last_event_id`; update `tests/abench_ui/test_ws_buffer.py` expectations to exclusive semantics (this is a correctness fix, not a weakening).
- Tests: batches listed newest-first incl. legacy; runs/summary/artefacts resolve per batch; session.started carries batch_id + isolation; replay exclusive.

### Task 3 — Frontend: API types/queries + batch routing
**Files:** `web/src/api/types.ts`, `web/src/api/queries.ts`, `web/src/ws/envelope.ts`, `web/src/routes.tsx`, `web/src/pages/ExperimentResults.tsx`, `web/src/pages/RunsIndex.tsx`, `web/src/components/TraceRunSwitcher.tsx`, `web/src/pages/TraceView.tsx`, tests.
- Types: `RunBatch {id, started_at, total_runs, valid_runs, success_rate}`; add `batch_id` to `SessionStarted` + `RunFinished` envelopes; thread `batch` through run/summary/artefact query keys + URLs (`?batch=`).
- Queries: `useBatches(name)`; `useRuns`/`useRunsSummary`/`useTrace`/`useEvents`/`useMetrics`/`usePatch`/`useVerifyLog` gain an optional `batch` arg passed as `?batch=`.
- Routing/UI: `ExperimentResults` gets a **batch selector** (dropdown, default newest) driving the comparison + runs table + TraceView links. `TraceView` reads `?batch=` (search param) and passes it to its data hooks + `TraceRunSwitcher`. Keep back-compat: missing `batch` → newest.
- Tests: batch selector renders + switches; trace/summary hooks request the selected batch.

### Task 4 — Frontend: live-run fixes
**Files:** `web/src/ws/useRunSession.ts`, `web/src/pages/Run.tsx`, `web/src/components/RunSidebar.tsx`, `web/src/components/RunSidebarCard.tsx`, `web/src/components/ProgressHeader.tsx`, `web/src/components/VerifyChip.tsx`, `web/src/components/IsolationChip.tsx`, tests.
- `useRunSession`: dedup — only append envelope when `event_id > lastIdRef` (or no numeric id); update `lastIdRef`. Add/adjust a test that replays a duplicate event id and asserts it's appended once.
- `Run.tsx`: read real `isolation` + `batch_id` from `session.started` (no hardcode); pass `experimentName` + `batch_id` to `RunSidebar`; add a polling backstop via `useRuns(name, batch, { refetchInterval })` while `!sessionFinished`.
- `RunSidebar`/`RunSidebarCard`: make cards clickable → `navigate(/runs/<exp>/<cond>/<rep>?batch=<id>)` when the run is `done` (or has artefacts); merge live-envelope state with the polled runs list. Show per-run verify status.
- `VerifyChip` + `ProgressHeader`: `passed/total` with the real status; stop hardcoding `"passed"`.
- `IsolationChip`: MUI Lock/LockOpen icon + a `Tooltip` explaining nonce/shuffle.
- Tests: dedup; isolation chip reflects props + tooltip; verify badge shows passed/total; sidebar card navigates.

### Task 5 — Emoji → MUI icons sweep
**Files:** all listed in Design; their tests.
- Replace every emoji with the mapped `@mui/icons-material` icon; preserve color/severity semantics. Update tests that matched emoji text to match the icon (`aria-label`/`data-testid`/role). Run the full suite + tsc.

### Task 6 — fixture/reference clarity
**Files:** `web/src/components/FixturesPanel.tsx`, test.
- Add concise captions/tooltips for fixture vs reference (text per Design). Test asserts the explanatory text/tooltip is present.

### Task 7 — Integration + boot/render smoke + final review
- Frontend: `npm test -- --run` green, `npx tsc -b` clean, `npm run build`.
- Python: full suite minus the 2 env e2e.
- Boot smoke: seed an experiment with TWO timestamped batches (+ optionally a legacy flat dir); confirm via the live server: batches listed newest-first, switching batch changes the comparison/trace, a fresh run creates a NEW batch (doesn't overwrite), live sidebar updates + a done card opens its trace, isolation chip shows real config with tooltip, verify badge shows passed/total, no emoji remain (grep `web/src` for the emoji set → empty), fixture/reference captions present.
- Final cross-cutting code review.

---

## Self-review notes
- Back-compat: legacy flat runs surface as a `"legacy"` batch (no data loss); new runs are timestamped batches.
- The batch is a query param (`?batch=`), not a new path segment, to minimize route churn; newest-by-default keeps existing deep links working.
- Live-run dedup is fixed on BOTH ends (server exclusive replay + client skip-seen) — defense in depth.
- Emoji removal must not weaken tests: swap text matchers for icon `aria-label`/testid with the same intent.
