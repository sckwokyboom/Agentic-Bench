# Web UI UX redesign — design spec

**Date:** 2026-05-29
**Status:** approved (brainstorm)
**Builds on:** the Plan B frontend (`web/`) + `abench_ui/` backend already shipped.

## Problem

The shipped UI works but is hard to navigate and read:

1. **No obvious path to results.** The only way to reach a run's trace is through
   *Edit experiment* → "Previous runs" panel. Viewing results by editing the
   experiment is unintuitive.
2. **No experiment-level view.** There is nowhere to see the baseline-vs-augmented
   summary (the whole point of the tool) in the browser — it exists only in the
   CLI's `summary.md`.
3. **Trace switching is hidden.** TraceView's only switcher is an easy-to-miss
   prev/next footer.
4. **Agent traces read as a dense, dry wall** — hard to scan turns/roles.
5. **Everything looks editable.** Default text cursor + selection on all chrome
   (labels, headings) makes static text look like input fields.
6. **Unclear affordances + "dumb blue."** Hard to tell buttons from text; the MUI
   blue primary should become dark-gray/near-black.

(Live-run output readability — dark-on-dark agent text — and the light/dark theme
toggle were already fixed in a prior change and are folded into the color work here.)

## Goals

A clear results-first information architecture, an in-browser baseline-vs-augmented
summary, frictionless trace switching, airier trace rendering, and a neutral visual
language where buttons look like buttons and static text does not look editable —
all readable in both light and dark themes.

## Non-goals (deferred)

- Editing `success` from the UI (the `usePatchSuccess` hook exists; no UI surfaced here).
- Bundle code-splitting.
- Full-screen `/diff` and `/compare` deep-link pages (inline expansion remains).

## Information architecture

Top nav (AppBar): **Experiments · Runs · [theme toggle]**.

| Route | Page | Purpose |
|---|---|---|
| `/experiments` | ExperimentList (revised) | list + actions |
| `/runs` | **RunsIndex (new)** | global index of experiments that have runs |
| `/runs/:name` | **ExperimentResults (new)** | aggregate summary + per-run table |
| `/runs/sessions/:sid` | Run (live, unchanged) | live ReAct stream |
| `/runs/:name/:condition/:rep` | TraceView (revised) | one trace + run-switcher sidebar |
| `/experiments/:name` | ExperimentEdit (unchanged) | edit form; keeps "Previous runs" panel |

### ExperimentList (revised)

- Row actions become: `▶ Run`, **`📊 Results`** (→ `/runs/:name`), `✎ Edit`, `🗑 Delete`.
- The experiment **name is a link to `/runs/:name`** (results), not to Edit.
- Edit remains reachable via the `✎` action only.

### RunsIndex (`/runs`, new)

A table of experiments that have at least one run (`has_runs === true`): name
(link → `/runs/:name`) and last-run timestamp, both already in `GET /api/experiments`
(`has_runs`, `last_run_at`) — so the index renders from a single request with no
per-experiment fan-out. Run count and success rate are **deferred** (they would
require an N-request fan-out; revisit if wanted). Empty state: "No runs yet — start
one from Experiments."

### ExperimentResults (`/runs/:name`, new) — the main results page

- **Top: aggregate baseline-vs-augmented table.** Mean/median per condition with
  the `augmented vs baseline` delta in percent for: `n_steps`, `n_reads`,
  `n_searches`, `n_test_runs`, `duration_s`, `time_to_first_edit_s`, `cost`,
  `success_rate`. Negative deltas on the cost-like metrics are tinted positive
  (green) = the RAG effect; positive = red. Source: new
  `GET /api/runs/:name/summary` reusing `report.summarize` (identical numbers to
  the CLI `summary.md`). If only one condition has runs, render the per-condition
  stats without deltas.
- **Below: per-run table** (condition × rep): verify chip, success, and headline
  metrics (duration, steps, tool calls, test runs, cost). Row click → trace.
  Rows are obviously clickable (pointer cursor + hover highlight). Source:
  `GET /api/runs/:name` extended with headline metrics (see backend changes).
- Loading/error/empty states for both sections.

## TraceView (revised)

- **Left run-switcher sidebar:** all runs of the experiment grouped by condition,
  reps within; the current run highlighted; click switches to
  `/runs/:name/:condition/:rep` without leaving the page. Uses `useRuns(name)`.
  This replaces reliance on the footer (prev/next may remain as a secondary aid).
- **Header summary:** the existing VerdictBanner + AggregateStatsBar, kept
  prominent so a per-trace summary is visible immediately.
- **Airier turn timeline** (addresses "too dense/dry"): each `TurnCard` gets
  - a clear header line: `turn N · <role> · <reason chip>`;
  - vertical spacing between parts;
  - per-role visual markers (icon + accent): 💭 reasoning, ✎ tool-call,
    ✓ tool-result, 🗨 text, ⚠ error;
  - long reasoning / tool output collapsible (show first N lines + "show more");
  - per-turn stats (tokens / cost / duration) as a muted footer;
  - the raw-events toggle remains.
  Colors use theme-aware tokens that read in both light and dark (no hardcoded
  dark-on-light or light-on-dark).

## Visual language

### Color — remove blue, go neutral-dark

- `theme.primary.main` → dark-gray/near-black (light mode ≈ `#1f2937`, a darker
  hover; dark mode a correspondingly light-neutral so contrast holds). Applied via
  the existing `makeTheme(mode)` factory so both themes stay consistent.
- The AppBar, contained buttons, chips, focus rings, and selected states inherit
  the neutral primary — no blue anywhere by default.

### Affordances — buttons look like buttons

- Primary actions: `variant="contained"` (solid neutral-dark fill).
- Secondary actions: `variant="outlined"`.
- Icon actions: always a `Tooltip` + visible hover background.
- No plain colored text that is not a link. Real links (experiment name, run rows)
  get link styling / pointer cursor + hover affordance.

### Cursor & selection — static text must not look editable

- Global baseline (via theme `CssBaseline`/`MuiCssBaseline` `styleOverrides` or a
  root `sx`): `body { cursor: default }`.
- `user-select: none` on chrome: headings, captions/labels, table headers, buttons,
  chips, nav links, panel titles.
- `user-select: text` + text cursor only on genuine **content** the user may copy:
  code, diffs, the trace event/turn output, raw-event JSON, and metric values.
- Clickable table rows: `cursor: pointer` + hover background.

Implementation approach: centralize via theme `components` overrides where possible
(e.g. default `MuiTypography` to `userSelect: none` and opt content back in with a
shared `selectable` sx helper), to avoid scattering rules.

## Backend changes (minimal, additive)

1. **`GET /api/runs/{name}/summary`** — returns the aggregate as JSON by reusing
   `abench.report.load_runs(root)` + `report.summarize(df)`. Shape:
   `{ conditions: [{ name, metrics: { <metric>: { mean, median } } }, ...],
   deltas: { <metric>: <pct augmented-vs-baseline> } }`. **Deltas are computed
   server-side** (same formula as the CLI `_to_markdown`) so the frontend only
   renders. When fewer than two conditions have runs, `deltas` is empty/omitted and
   the frontend shows per-condition stats only. 404 if the experiment or its runs
   dir is absent; empty runs handled gracefully.
2. **Extend `runs.list_runs`** (and the `GET /api/runs/{name}` response +
   `RunSummary` type) with headline metrics already present in each `metrics.json`:
   `duration_s`, `n_steps`, `n_tool_calls`, `n_test_runs`, `cost`. This lets the
   per-run table render from one request instead of N metric fetches.

Both reuse existing logic (`report.py`, `metrics.json`) — no new computation paths,
so UI numbers match the CLI.

## Components & files (indicative)

New frontend:
- `web/src/pages/RunsIndex.tsx`, `web/src/pages/ExperimentResults.tsx`
- `web/src/components/SummaryTable.tsx` (aggregate baseline-vs-augmented)
- `web/src/components/RunsTable.tsx` (per-run rows)
- `web/src/components/TraceRunSwitcher.tsx` (sidebar)
- API hooks: `useRunsSummary(name)`; extend `RunSummary` type + `useRuns`.

Revised:
- `web/src/App.tsx` (nav: add Runs; toggle already present), `routes.tsx` (+2 routes)
- `web/src/pages/ExperimentList.tsx` (name link + Results action)
- `web/src/pages/TraceView.tsx` (+ switcher sidebar, layout)
- `web/src/components/TurnCard.tsx` (airier, collapsible, role markers)
- `web/src/theme.tsx` (neutral primary, CssBaseline cursor/select overrides)
- a small `selectable` sx helper (e.g. `web/src/theme.tsx` export or `web/src/lib/`).

Backend:
- `abench_ui/server.py` (+ `/runs/{name}/summary` route)
- `abench_ui/runs.py` (`list_runs` headline metrics; maybe a `summarize_runs` wrapper)

## Testing

- **Python:** unit test for the new summary endpoint (aggregate matches
  `report.summarize` on a fixture run dir; 404 on missing); `list_runs` includes the
  new headline-metric fields.
- **Frontend:** component tests for `SummaryTable` (delta sign/coloring),
  `RunsTable` (renders rows, row→trace navigation), `TraceRunSwitcher` (highlights
  current, switches), and the revised `TurnCard` (role markers, collapse).
- **Visual/contrast:** buttons and static text remain legible in both themes;
  static text is not selectable, content is. (Verified by the user in-browser;
  optionally a preview-tool screenshot pass on the key pages in both modes.)

## Risks / notes

- `report.summarize` returns a pandas DataFrame; the endpoint must serialize it to
  JSON cleanly (NaN → null, numpy types → native). Cover in the unit test.
- Centralizing `user-select`/`cursor` via theme overrides risks disabling selection
  on content too; the `selectable` opt-in helper must be applied to all content
  surfaces (code/diff/trace/metric values). Call this out in the plan.
- Keep the live `Run` page (`/runs/sessions/:sid`) unchanged except inheriting the
  new neutral theme.
