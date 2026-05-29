# Web UI UX Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Agentic-Bench Web UI results-first and legible — a Runs index + per-experiment Results page with an in-browser baseline-vs-augmented summary, a TraceView run-switcher with airier turn cards, and a neutral-dark visual language where buttons look like buttons and static text isn't mistaken for editable.

**Architecture:** Two additive backend endpoints reuse existing aggregation (`abench.report`) and per-run reading (`abench_ui.runs`). The frontend adds two pages (RunsIndex, ExperimentResults) + three components (SummaryTable, RunsTable, TraceRunSwitcher), revises ExperimentList/TraceView/TurnCard, and centralizes the visual language (neutral primary, cursor/selection rules) in the theme.

**Tech Stack:** Python 3.12 (FastAPI, pandas), React 18 + TypeScript + MUI v5 + TanStack Query + react-router-dom v6, Vitest + Testing Library, pytest.

**Spec:** `docs/superpowers/specs/2026-05-29-web-ui-ux-redesign-design.md`

**Conventions (already in this repo):**
- Python venv: run tests with `.venv/bin/pytest`.
- Frontend: run from `web/`. `npm test -- --run` (Vitest), `npx tsc -b` (typecheck).
- `tsconfig.json` has `strict` + `noUncheckedIndexedAccess` — indexed access needs `!`/`?.`/`?? fallback`.
- Stay on `main`. Commit after each task.

---

## Task 1: Backend — `report.summary_json(root)` aggregation

**Files:**
- Modify: `abench/report.py`
- Test: `tests/test_report.py` (create if absent; otherwise append)

- [ ] **Step 1: Write the failing test**

`tests/test_report.py` (append; if creating, add `from pathlib import Path` + `import json`):
```python
import json
from pathlib import Path

from abench import report


def _write_run(root: Path, condition: str, rep: int, metrics: dict) -> None:
    d = root / condition / f"rep_{rep}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "metrics.json").write_text(json.dumps(metrics))
    (d / "manifest.json").write_text(json.dumps({"condition": condition, "rep": rep}))


def test_summary_json_means_and_deltas(tmp_path: Path):
    root = tmp_path / "runs"
    base = {"interrupted_reason": None, "success": True}
    _write_run(root, "baseline", 0, {**base, "n_steps": 10, "duration_s": 100.0, "cost": 0.02})
    _write_run(root, "baseline", 1, {**base, "n_steps": 20, "duration_s": 200.0, "cost": 0.04})
    _write_run(root, "augmented", 0, {**base, "n_steps": 6, "duration_s": 80.0, "cost": 0.03})
    _write_run(root, "augmented", 1, {**base, "n_steps": 6, "duration_s": 120.0, "cost": 0.03})

    out = report.summary_json(root)

    assert out["total_runs"] == 4
    assert out["valid_runs"] == 4
    conds = {c["name"]: c for c in out["conditions"]}
    assert conds["baseline"]["metrics"]["n_steps"]["mean"] == 15.0
    assert conds["augmented"]["metrics"]["n_steps"]["mean"] == 6.0
    assert conds["baseline"]["success_rate"] == 1.0
    # delta = (6 - 15) / 15 * 100 = -60.0
    assert out["deltas"]["n_steps"] == -60.0


def test_summary_json_excludes_interrupted_and_handles_empty(tmp_path: Path):
    root = tmp_path / "runs"
    _write_run(root, "baseline", 0, {"interrupted_reason": "timeout", "success": None, "n_steps": 99})
    out = report.summary_json(root)
    # the only run is interrupted → excluded from condition stats
    assert out["total_runs"] == 1
    assert out["valid_runs"] == 0
    assert out["conditions"] == []
    assert out["deltas"] == {}

    empty = report.summary_json(tmp_path / "nope")
    assert empty == {"conditions": [], "deltas": {}, "total_runs": 0, "valid_runs": 0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_report.py -k summary_json -v`
Expected: FAIL with `AttributeError: module 'abench.report' has no attribute 'summary_json'`.

- [ ] **Step 3: Implement `summary_json`**

Append to `abench/report.py` (after `summarize`):
```python
def summary_json(root: Path) -> dict:
    """JSON-friendly aggregate for the Web UI. Reuses load_runs; means/medians
    per condition over valid runs (interrupted excluded), plus augmented-vs-
    baseline percent deltas. NaN → None; numpy scalars → native floats."""
    df = load_runs(Path(root))
    if df.empty:
        return {"conditions": [], "deltas": {}, "total_runs": 0, "valid_runs": 0}

    valid = df[df["interrupted_reason"].isna()]
    total_runs = int(len(df))
    valid_runs = int(len(valid))
    if valid.empty:
        return {"conditions": [], "deltas": {}, "total_runs": total_runs, "valid_runs": valid_runs}

    mean = valid.groupby("condition")[NUMERIC].mean()
    median = valid.groupby("condition")[NUMERIC].median()

    conditions = []
    for cond in mean.index:
        sub = valid[valid["condition"] == cond]
        succ = sub["success"].dropna()
        success_rate = (
            float((succ == True).sum()) / len(succ) if len(succ) else None  # noqa: E712
        )
        metrics = {}
        for m in NUMERIC:
            mv = mean.loc[cond, m]
            dv = median.loc[cond, m]
            metrics[m] = {
                "mean": None if pd.isna(mv) else float(mv),
                "median": None if pd.isna(dv) else float(dv),
            }
        conditions.append({
            "name": str(cond),
            "runs": int(len(sub)),
            "success_rate": success_rate,
            "metrics": metrics,
        })

    deltas: dict[str, float] = {}
    names = list(mean.index)
    if "baseline" in names and "augmented" in names:
        for m in NUMERIC:
            base = mean.loc["baseline", m]
            aug = mean.loc["augmented", m]
            if not pd.isna(base) and not pd.isna(aug) and base != 0:
                deltas[m] = round(float((aug - base) / base * 100), 1)

    return {
        "conditions": conditions,
        "deltas": deltas,
        "total_runs": total_runs,
        "valid_runs": valid_runs,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_report.py -k summary_json -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add abench/report.py tests/test_report.py
git commit -m "feat(report): summary_json aggregate for the web UI"
```

---

## Task 2: Backend — `GET /api/runs/{name}/summary` endpoint

**Files:**
- Modify: `abench_ui/server.py` (import `report`; add route after `/runs/{name}`)
- Test: `tests/abench_ui/test_runs_api.py` (append; create if absent)

- [ ] **Step 1: Write the failing test**

Append to `tests/abench_ui/test_runs_api.py` (if creating, mirror the fixture style of `tests/abench_ui/test_static.py`):
```python
import json
from pathlib import Path

from fastapi.testclient import TestClient

from abench_ui.server import create_app


def _seed_run(exp_dir: Path, name: str, condition: str, rep: int, metrics: dict) -> None:
    d = exp_dir / name / "runs" / name / condition / f"rep_{rep}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "metrics.json").write_text(json.dumps(metrics))
    (d / "manifest.json").write_text(json.dumps({"condition": condition, "rep": rep}))


def test_runs_summary_endpoint(tmp_path: Path):
    exp_dir = tmp_path / "experiments"
    base = {"interrupted_reason": None, "success": True, "n_steps": 10, "duration_s": 100.0}
    _seed_run(exp_dir, "exp", "baseline", 0, base)
    _seed_run(exp_dir, "exp", "augmented", 0, {**base, "n_steps": 5})
    app = create_app(experiments_dir=exp_dir)
    client = TestClient(app)

    resp = client.get("/api/runs/exp/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_runs"] == 2
    names = {c["name"] for c in body["conditions"]}
    assert names == {"baseline", "augmented"}
    assert body["deltas"]["n_steps"] == -50.0


def test_runs_summary_404_when_no_runs(tmp_path: Path):
    exp_dir = tmp_path / "experiments"
    (exp_dir / "exp").mkdir(parents=True)
    app = create_app(experiments_dir=exp_dir)
    client = TestClient(app)
    resp = client.get("/api/runs/exp/summary")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/abench_ui/test_runs_api.py -k summary -v`
Expected: FAIL (404 for the first test — route not registered yet).

- [ ] **Step 3: Add the import and route**

In `abench_ui/server.py`, add the import near the other `abench` imports at the top:
```python
from abench import report
```
Then add this route immediately AFTER the `@api.get("/runs/{name}")` handler (around line 164), BEFORE `@api.get("/runs/{name}/{condition}/{rep}/metrics")`:
```python
    @api.get("/runs/{name}/summary")
    def _runs_summary(name: str):
        runs_dir = _exp_dir_for(name) / "runs" / name
        if not runs_dir.is_dir():
            raise HTTPException(404, f"no runs for '{name}'")
        return report.summary_json(runs_dir)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/abench_ui/test_runs_api.py -k summary -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add abench_ui/server.py tests/abench_ui/test_runs_api.py
git commit -m "feat(ui/server): GET /api/runs/{name}/summary"
```

---

## Task 3: Backend — headline metrics in `list_runs`

**Files:**
- Modify: `abench_ui/runs.py` (`list_runs`)
- Test: `tests/abench_ui/test_runs_list.py` (append; create if absent)

- [ ] **Step 1: Write the failing test**

Append to `tests/abench_ui/test_runs_list.py`:
```python
import json
from pathlib import Path

from abench_ui import runs


def test_list_runs_includes_headline_metrics(tmp_path: Path):
    d = tmp_path / "baseline" / "rep_0"
    d.mkdir(parents=True)
    (d / "metrics.json").write_text(json.dumps({
        "finished": True, "interrupted_reason": None, "verify_status": "passed",
        "success": True, "duration_s": 123.4, "n_steps": 7, "n_tool_calls": 12,
        "n_test_runs": 2, "cost": 0.0123,
    }))
    items = runs.list_runs(tmp_path)
    assert len(items) == 1
    it = items[0]
    assert it["duration_s"] == 123.4
    assert it["n_steps"] == 7
    assert it["n_tool_calls"] == 12
    assert it["n_test_runs"] == 2
    assert it["cost"] == 0.0123
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/abench_ui/test_runs_list.py -v`
Expected: FAIL with `KeyError: 'duration_s'`.

- [ ] **Step 3: Add the fields**

In `abench_ui/runs.py`, in `list_runs`, extend the appended dict (currently ends with `"started_at": _mtime_iso(m_path)`):
```python
            items.append({
                "condition": cond_dir.name,
                "rep": int(rep_dir.name.removeprefix("rep_")),
                "finished": m.get("finished"),
                "interrupted_reason": m.get("interrupted_reason"),
                "verify_status": m.get("verify_status"),
                "success": m.get("success"),
                "started_at": _mtime_iso(m_path),
                "duration_s": m.get("duration_s"),
                "n_steps": m.get("n_steps"),
                "n_tool_calls": m.get("n_tool_calls"),
                "n_test_runs": m.get("n_test_runs"),
                "cost": m.get("cost"),
            })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/abench_ui/test_runs_list.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full Python suite (no regressions)**

Run: `.venv/bin/pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add abench_ui/runs.py tests/abench_ui/test_runs_list.py
git commit -m "feat(ui/server): headline metrics in list_runs"
```

---

## Task 4: Frontend — neutral visual language (theme: color, cursor, selection)

**Files:**
- Modify: `web/src/theme.tsx` (neutral primary per-mode; CssBaseline cursor; `selectable` helper)
- Modify: `web/src/App.tsx` (AppBar `color="default"`)
- Test: `web/tests/theme.test.ts` (create)

- [ ] **Step 1: Write the failing test**

`web/tests/theme.test.ts`:
```ts
import { expect, test } from "vitest";
import { makeTheme, selectable } from "../src/theme";

test("primary is a neutral (non-blue) color in both modes", () => {
  const light = makeTheme("light");
  const dark = makeTheme("dark");
  // dark-gray in light mode, light-neutral in dark mode — never MUI blue (#1976d2)
  expect(light.palette.primary.main.toLowerCase()).toBe("#1f2937");
  expect(dark.palette.primary.main.toLowerCase()).toBe("#cbd5e1");
  expect(light.palette.primary.main).not.toBe("#1976d2");
});

test("selectable helper opts content back into text selection", () => {
  expect(selectable).toEqual({ userSelect: "text", cursor: "text" });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `web/`): `npm test -- --run tests/theme.test.ts`
Expected: FAIL (`selectable` not exported; primary not set).

- [ ] **Step 3: Update `makeTheme` + export `selectable`**

In `web/src/theme.tsx`, replace the `makeTheme` body's `palette`/add `components`, and add the `selectable` export. The full updated `makeTheme` + helper:
```tsx
export const selectable = { userSelect: "text", cursor: "text" } as const;

export function makeTheme(mode: ColorMode): Theme {
  const primary =
    mode === "dark"
      ? { main: "#cbd5e1", contrastText: "#0d1117" }   // light-neutral on dark
      : { main: "#1f2937", contrastText: "#ffffff" };   // dark-gray on light
  return createTheme({
    palette: {
      mode,
      primary,
      ...(mode === "dark"
        ? { background: { default: "#0d1117", paper: "#161b22" } }
        : { background: { default: "#fafafa", paper: "#ffffff" } }),
    },
    typography: {
      fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
      fontSize: 14,
    },
    shape: { borderRadius: 6 },
    components: {
      MuiCssBaseline: {
        styleOverrides: {
          // Static UI text must not look editable. Chrome is non-selectable with
          // a default cursor; genuine content opts back in via `selectable`.
          body: { cursor: "default", userSelect: "none" },
        },
      },
    },
  });
}
```
(Keep the existing imports — `createTheme`, `ThemeProvider`, `type Theme`, `CssBaseline` — and the rest of the file: `ColorMode`, `ColorModeContext`, `useColorMode`, `ColorModeProvider`.)

- [ ] **Step 4: AppBar to neutral**

In `web/src/App.tsx`, change the AppBar so it is neutral in both modes (not the primary fill). Replace:
```tsx
      <AppBar position="static">
```
with:
```tsx
      <AppBar position="static" color="default" enableColorOnDark>
```

- [ ] **Step 5: Run tests to verify pass**

Run: `npm test -- --run tests/theme.test.ts` → PASS.
Run: `npm test -- --run tests/ColorMode.test.tsx` → still PASS (toggle/persist unaffected).

- [ ] **Step 6: Typecheck**

Run: `npx tsc -b`
Expected: clean (exit 0).

- [ ] **Step 7: Commit**

```bash
git add web/src/theme.tsx web/src/App.tsx web/tests/theme.test.ts
git commit -m "feat(ui/web): neutral-dark theme + cursor/selection baseline"
```

---

## Task 5: Frontend — summary types + hooks

**Files:**
- Modify: `web/src/api/types.ts` (extend `RunSummary`; add `RunsSummary`/`ConditionSummary`)
- Modify: `web/src/api/queries.ts` (add `qk.runsSummary`, `useRunsSummary`)

- [ ] **Step 1: Extend `RunSummary` and add summary types**

In `web/src/api/types.ts`, replace the `RunSummary` interface with:
```ts
export interface RunSummary {
  condition: string;
  rep: number;
  finished: boolean;
  interrupted_reason: string | null;
  verify_status: VerifyStatus | null;
  success: boolean | null;
  started_at: string;
  duration_s: number | null;
  n_steps: number | null;
  n_tool_calls: number | null;
  n_test_runs: number | null;
  cost: number | null;
}

export interface ConditionSummary {
  name: string;
  runs: number;
  success_rate: number | null;
  metrics: Record<string, { mean: number | null; median: number | null }>;
}

export interface RunsSummary {
  conditions: ConditionSummary[];
  deltas: Record<string, number>;
  total_runs: number;
  valid_runs: number;
}
```

- [ ] **Step 2: Add the query key + hook**

In `web/src/api/queries.ts`, add to the `qk` object (after `runs`):
```ts
  runsSummary: (name: string) => ["runsSummary", name] as const,
```
And add the hook after `useRuns`:
```ts
export const useRunsSummary = (name: string | undefined) =>
  useQuery({
    queryKey: qk.runsSummary(name ?? ""),
    enabled: Boolean(name),
    queryFn: () => apiGet<t.RunsSummary>(`/api/runs/${name}/summary`),
  });
```

- [ ] **Step 3: Typecheck**

Run: `npx tsc -b`
Expected: clean. (No component consumes these yet; this is the contract layer.)

- [ ] **Step 4: Commit**

```bash
git add web/src/api/types.ts web/src/api/queries.ts
git commit -m "feat(ui/web): RunsSummary types + useRunsSummary hook"
```

---

## Task 6: Frontend — SummaryTable component

**Files:**
- Create: `web/src/lib/metricLabels.ts`
- Create: `web/src/components/SummaryTable.tsx`
- Test: `web/tests/SummaryTable.test.tsx`

- [ ] **Step 1: Create the metric-label map**

`web/src/lib/metricLabels.ts`:
```ts
// Order + display labels for the summary table. "lowerIsBetter" decides delta
// coloring: a negative delta on these is the desired RAG effect (green).
export const SUMMARY_METRICS: { key: string; label: string; lowerIsBetter: boolean }[] = [
  { key: "n_steps", label: "steps", lowerIsBetter: true },
  { key: "n_reads", label: "reads", lowerIsBetter: true },
  { key: "n_searches", label: "searches", lowerIsBetter: true },
  { key: "n_test_runs", label: "test runs", lowerIsBetter: true },
  { key: "duration_s", label: "duration (s)", lowerIsBetter: true },
  { key: "time_to_first_edit_s", label: "time to first edit (s)", lowerIsBetter: true },
  { key: "n_tool_calls", label: "tool calls", lowerIsBetter: true },
  { key: "cost", label: "cost ($)", lowerIsBetter: true },
];
```

- [ ] **Step 2: Write the failing test**

`web/tests/SummaryTable.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import SummaryTable from "../src/components/SummaryTable";
import type { RunsSummary } from "../src/api/types";

const summary: RunsSummary = {
  total_runs: 4,
  valid_runs: 4,
  conditions: [
    { name: "baseline", runs: 2, success_rate: 1,
      metrics: { n_steps: { mean: 15, median: 15 }, cost: { mean: 0.03, median: 0.03 } } },
    { name: "augmented", runs: 2, success_rate: 1,
      metrics: { n_steps: { mean: 6, median: 6 }, cost: { mean: 0.03, median: 0.03 } } },
  ],
  deltas: { n_steps: -60, cost: 0 },
};

test("renders condition columns, metric means and the delta", () => {
  render(<SummaryTable summary={summary} />);
  // header cells render "baseline (n=2)" / "augmented (n=2)" → match by regex
  expect(screen.getByText(/baseline/)).toBeInTheDocument();
  expect(screen.getByText(/augmented/)).toBeInTheDocument();
  expect(screen.getByText("steps")).toBeInTheDocument();
  expect(screen.getByText("15.00")).toBeInTheDocument(); // baseline mean
  expect(screen.getByText("6.00")).toBeInTheDocument();  // augmented mean
  expect(screen.getByText("-60.0%")).toBeInTheDocument();
});

test("shows an empty-state when no valid runs", () => {
  render(<SummaryTable summary={{ conditions: [], deltas: {}, total_runs: 0, valid_runs: 0 }} />);
  expect(screen.getByText(/no aggregate/i)).toBeInTheDocument();
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `npm test -- --run tests/SummaryTable.test.tsx`
Expected: FAIL (component missing).

- [ ] **Step 4: Implement `SummaryTable`**

`web/src/components/SummaryTable.tsx`:
```tsx
import {
  Table, TableHead, TableBody, TableRow, TableCell, Typography, Box,
} from "@mui/material";
import { selectable } from "../theme";
import { SUMMARY_METRICS } from "../lib/metricLabels";
import type { RunsSummary } from "../api/types";

interface Props { summary: RunsSummary; }

function fmt(v: number | null | undefined): string {
  return v == null ? "—" : v.toFixed(2);
}

export default function SummaryTable({ summary }: Props) {
  if (summary.conditions.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        No aggregate yet — runs may be in progress or all interrupted.
      </Typography>
    );
  }
  const conditions = summary.conditions;
  const hasDelta = Object.keys(summary.deltas).length > 0;
  return (
    <Box sx={{ border: 1, borderColor: "divider", borderRadius: 1, overflow: "auto" }}>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>metric</TableCell>
            {conditions.map((c) => (
              <TableCell key={c.name} align="right">{c.name} (n={c.runs})</TableCell>
            ))}
            {hasDelta && <TableCell align="right">Δ aug vs base</TableCell>}
          </TableRow>
        </TableHead>
        <TableBody>
          {SUMMARY_METRICS.map((m) => {
            const delta = summary.deltas[m.key];
            const good = delta != null && (m.lowerIsBetter ? delta < 0 : delta > 0);
            const bad = delta != null && delta !== 0 && !good;
            return (
              <TableRow key={m.key} hover>
                <TableCell>{m.label}</TableCell>
                {conditions.map((c) => (
                  <TableCell key={c.name} align="right" sx={selectable}>
                    {fmt(c.metrics[m.key]?.mean)}
                  </TableCell>
                ))}
                {hasDelta && (
                  <TableCell
                    align="right"
                    sx={{ color: good ? "success.main" : bad ? "error.main" : "text.secondary" }}
                  >
                    {delta == null ? "—" : `${delta > 0 ? "+" : ""}${delta.toFixed(1)}%`}
                  </TableCell>
                )}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </Box>
  );
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npm test -- --run tests/SummaryTable.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/metricLabels.ts web/src/components/SummaryTable.tsx web/tests/SummaryTable.test.tsx
git commit -m "feat(ui/web): SummaryTable (baseline vs augmented deltas)"
```

---

## Task 7: Frontend — RunsTable component

**Files:**
- Create: `web/src/components/VerifyStatusChip.tsx`
- Create: `web/src/components/RunsTable.tsx`
- Test: `web/tests/RunsTable.test.tsx`

> Why `VerifyStatusChip`: the existing `VerifyChip` renders pass/fail **counts**
> (`🧪 ?/?`) for `passed`/`failed`, but `RunSummary` carries no counts — only the
> status. `VerifyStatusChip` shows the status **word** + color, for the runs list
> and the trace switcher (Task 11).

- [ ] **Step 0: Create `VerifyStatusChip`**

`web/src/components/VerifyStatusChip.tsx`:
```tsx
import { Chip } from "@mui/material";
import type { VerifyStatus } from "../api/types";

const color: Record<string, "success" | "error" | "warning" | "default"> = {
  passed: "success", failed: "error", timeout: "warning", error: "warning", skipped: "default",
};

export default function VerifyStatusChip({ status }: { status: VerifyStatus | null }) {
  if (!status) return <Chip size="small" variant="outlined" label="—" />;
  return <Chip size="small" color={color[status] ?? "default"} label={status} />;
}
```

- [ ] **Step 1: Write the failing test**

`web/tests/RunsTable.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import RunsTable from "../src/components/RunsTable";
import type { RunSummary } from "../src/api/types";

const rows: RunSummary[] = [
  { condition: "baseline", rep: 0, finished: true, interrupted_reason: null,
    verify_status: "passed", success: true, started_at: "2026-05-29T10:00:00",
    duration_s: 100, n_steps: 10, n_tool_calls: 12, n_test_runs: 2, cost: 0.02 },
];

test("renders a row and fires onOpen on row click", async () => {
  const onOpen = vi.fn();
  render(<RunsTable rows={rows} onOpen={onOpen} />);
  expect(screen.getByText("baseline")).toBeInTheDocument();
  expect(screen.getByText(/passed/i)).toBeInTheDocument();
  await userEvent.click(screen.getByText("baseline"));
  expect(onOpen).toHaveBeenCalledWith("baseline", 0);
});

test("empty-state when no runs", () => {
  render(<RunsTable rows={[]} onOpen={() => {}} />);
  expect(screen.getByText(/no runs/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- --run tests/RunsTable.test.tsx`
Expected: FAIL (component missing).

- [ ] **Step 3: Implement `RunsTable`**

`web/src/components/RunsTable.tsx`:
```tsx
import {
  Table, TableHead, TableBody, TableRow, TableCell, Typography, Box,
} from "@mui/material";
import VerifyStatusChip from "./VerifyStatusChip";
import { selectable } from "../theme";
import type { RunSummary } from "../api/types";

interface Props {
  rows: RunSummary[];
  onOpen: (condition: string, rep: number) => void;
}

function num(v: number | null | undefined, digits = 0): string {
  return v == null ? "—" : v.toFixed(digits);
}

export default function RunsTable({ rows, onOpen }: Props) {
  if (rows.length === 0) {
    return <Typography variant="body2" color="text.secondary">No runs yet.</Typography>;
  }
  return (
    <Box sx={{ border: 1, borderColor: "divider", borderRadius: 1 }}>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>condition</TableCell>
            <TableCell align="right">rep</TableCell>
            <TableCell>verify</TableCell>
            <TableCell>success</TableCell>
            <TableCell align="right">duration (s)</TableCell>
            <TableCell align="right">steps</TableCell>
            <TableCell align="right">tools</TableCell>
            <TableCell align="right">tests</TableCell>
            <TableCell align="right">cost ($)</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((r) => (
            <TableRow
              key={`${r.condition}-${r.rep}`}
              hover
              onClick={() => onOpen(r.condition, r.rep)}
              sx={{ cursor: "pointer" }}
            >
              <TableCell>{r.condition}</TableCell>
              <TableCell align="right">{r.rep}</TableCell>
              <TableCell><VerifyStatusChip status={r.verify_status} /></TableCell>
              <TableCell>{r.success == null ? "—" : r.success ? "✓" : "✗"}</TableCell>
              <TableCell align="right" sx={selectable}>{num(r.duration_s, 1)}</TableCell>
              <TableCell align="right" sx={selectable}>{num(r.n_steps)}</TableCell>
              <TableCell align="right" sx={selectable}>{num(r.n_tool_calls)}</TableCell>
              <TableCell align="right" sx={selectable}>{num(r.n_test_runs)}</TableCell>
              <TableCell align="right" sx={selectable}>{num(r.cost, 4)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- --run tests/RunsTable.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add web/src/components/VerifyStatusChip.tsx web/src/components/RunsTable.tsx web/tests/RunsTable.test.tsx
git commit -m "feat(ui/web): RunsTable + VerifyStatusChip (per-rep run list)"
```

---

## Task 8: Frontend — ExperimentResults page

**Files:**
- Create: `web/src/pages/ExperimentResults.tsx`

- [ ] **Step 1: Implement the page**

`web/src/pages/ExperimentResults.tsx`:
```tsx
import { useNavigate, useParams, Link as RouterLink } from "react-router-dom";
import {
  Stack, Typography, CircularProgress, Alert, Button, Box, Link,
} from "@mui/material";
import { useRuns, useRunsSummary } from "../api/queries";
import SummaryTable from "../components/SummaryTable";
import RunsTable from "../components/RunsTable";

export default function ExperimentResults() {
  const { name } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const runs = useRuns(name);
  const summary = useRunsSummary(name);

  return (
    <Stack spacing={3} sx={{ maxWidth: 1100, mx: "auto" }}>
      <Stack direction="row" alignItems="center" spacing={2}>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>Results · {name}</Typography>
        <Button component={RouterLink} to={`/experiments/${name}`} variant="outlined" size="small">
          Edit
        </Button>
      </Stack>

      <Box>
        <Typography variant="subtitle2" gutterBottom>Aggregate (baseline vs augmented)</Typography>
        {summary.isLoading && <CircularProgress size={20} />}
        {summary.error && <Alert severity="error">Failed to load summary.</Alert>}
        {summary.data && <SummaryTable summary={summary.data} />}
      </Box>

      <Box>
        <Typography variant="subtitle2" gutterBottom>Runs</Typography>
        {runs.isLoading && <CircularProgress size={20} />}
        {runs.error && <Alert severity="error">Failed to load runs.</Alert>}
        {runs.data && (
          <RunsTable
            rows={runs.data}
            onOpen={(condition, rep) => navigate(`/runs/${name}/${condition}/${rep}`)}
          />
        )}
      </Box>

      <Link component={RouterLink} to="/runs" variant="body2">← all experiments with runs</Link>
    </Stack>
  );
}
```

- [ ] **Step 2: Typecheck (page is wired into routes in Task 10)**

Run: `npx tsc -b`
Expected: clean. (Unused-until-routed is fine; `noUnusedLocals` is not set.)

- [ ] **Step 3: Commit**

```bash
git add web/src/pages/ExperimentResults.tsx
git commit -m "feat(ui/web): ExperimentResults page (summary + runs)"
```

---

## Task 9: Frontend — RunsIndex page

**Files:**
- Create: `web/src/pages/RunsIndex.tsx`
- Test: `web/tests/RunsIndex.test.tsx`

- [ ] **Step 1: Write the failing test**

`web/tests/RunsIndex.test.tsx`:
```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { expect, test } from "vitest";
import { mswServer } from "./setup";
import RunsIndex from "../src/pages/RunsIndex";

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  );
}

test("lists only experiments that have runs", async () => {
  mswServer.use(http.get("/api/experiments", () => HttpResponse.json([
    { name: "with-runs", has_fixture: true, has_reference: true, has_runs: true, last_run_at: "2026-05-29T10:00:00" },
    { name: "no-runs", has_fixture: true, has_reference: false, has_runs: false, last_run_at: null },
  ])));
  render(wrap(<RunsIndex />));
  await waitFor(() => expect(screen.getByText("with-runs")).toBeInTheDocument());
  expect(screen.queryByText("no-runs")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- --run tests/RunsIndex.test.tsx`
Expected: FAIL (component missing).

- [ ] **Step 3: Implement the page**

`web/src/pages/RunsIndex.tsx`:
```tsx
import { Link as RouterLink } from "react-router-dom";
import {
  Stack, Typography, CircularProgress, Alert, Box, Table, TableHead,
  TableBody, TableRow, TableCell, Link,
} from "@mui/material";
import { useExperiments } from "../api/queries";

export default function RunsIndex() {
  const list = useExperiments();
  const withRuns = (list.data ?? []).filter((e) => e.has_runs);

  return (
    <Stack spacing={2} sx={{ maxWidth: 900, mx: "auto" }}>
      <Typography variant="h5">Runs</Typography>
      {list.isLoading && <CircularProgress />}
      {list.error && <Alert severity="error">Failed to load experiments.</Alert>}
      {list.data && withRuns.length === 0 && (
        <Typography variant="body2" color="text.secondary">
          No runs yet — start one from Experiments.
        </Typography>
      )}
      {withRuns.length > 0 && (
        <Box sx={{ border: 1, borderColor: "divider", borderRadius: 1 }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>experiment</TableCell>
                <TableCell>last run</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {withRuns.map((e) => (
                <TableRow key={e.name} hover>
                  <TableCell>
                    <Link component={RouterLink} to={`/runs/${e.name}`}>{e.name}</Link>
                  </TableCell>
                  <TableCell>{e.last_run_at ?? "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      )}
    </Stack>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- --run tests/RunsIndex.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/RunsIndex.tsx web/tests/RunsIndex.test.tsx
git commit -m "feat(ui/web): RunsIndex page"
```

---

## Task 10: Frontend — routes + nav + ExperimentList revise

**Files:**
- Modify: `web/src/routes.tsx` (add `/runs`, `/runs/:name`)
- Modify: `web/src/App.tsx` (add "Runs" nav link)
- Modify: `web/src/pages/ExperimentList.tsx` (name → Results link; add Results action)

- [ ] **Step 1: Add the routes**

In `web/src/routes.tsx`, add imports and two child routes. Replace the imports block top with:
```tsx
import { createBrowserRouter, Navigate } from "react-router-dom";
import App from "./App";
import ExperimentList from "./pages/ExperimentList";
import ExperimentEdit from "./pages/ExperimentEdit";
import RunsIndex from "./pages/RunsIndex";
import ExperimentResults from "./pages/ExperimentResults";
import Run from "./pages/Run";
import TraceView from "./pages/TraceView";
```
And replace the `children` array with (note: `runs/:name` MUST come before `runs/:name/:condition/:rep`, and the static `runs/sessions/:sid` stays distinct):
```tsx
    children: [
      { index: true, element: <Navigate to="/experiments" replace /> },
      { path: "experiments", element: <ExperimentList /> },
      { path: "experiments/:name", element: <ExperimentEdit /> },
      { path: "runs", element: <RunsIndex /> },
      { path: "runs/sessions/:sid", element: <Run /> },
      { path: "runs/:name", element: <ExperimentResults /> },
      { path: "runs/:name/:condition/:rep", element: <TraceView /> },
    ],
```

- [ ] **Step 2: Add the "Runs" nav link**

In `web/src/App.tsx`, add a Runs link next to Experiments. After the existing
`<NavLink to="/experiments" ...>Experiments</NavLink>` line add:
```tsx
          <NavLink to="/runs" style={linkStyle}>Runs</NavLink>
```

- [ ] **Step 3: ExperimentList — name links to Results, add Results action**

In `web/src/pages/ExperimentList.tsx`:

(a) Add imports near the other icon imports:
```tsx
import AssessmentIcon from "@mui/icons-material/Assessment";
import { Link as RouterLink } from "react-router-dom";
import { Link } from "@mui/material";
```
(`Link` joins the existing `@mui/material` import — merge it into that import list rather than duplicating; if simpler, import it on its own line as shown.)

(b) Make the name a link. Replace:
```tsx
                  <TableCell>{e.name}</TableCell>
```
with:
```tsx
                  <TableCell>
                    <Link component={RouterLink} to={`/runs/${e.name}`}>{e.name}</Link>
                  </TableCell>
```

(c) Add a Results icon-button as the FIRST action (before Run). Inside the actions
`<TableCell align="right">`, before the Run `<IconButton ...>`, add:
```tsx
                    <IconButton
                      size="small"
                      title="Results"
                      onClick={() => navigate(`/runs/${e.name}`)}
                      aria-label="results"
                    >
                      <AssessmentIcon fontSize="small" />
                    </IconButton>
```

- [ ] **Step 4: Run the full frontend suite + typecheck**

Run: `npm test -- --run`
Expected: all green (existing ExperimentList test still passes — it asserts the row/actions render; the name is now a link but the text "….name" is still present).
Run: `npx tsc -b` → clean.

> If the existing `ExperimentList` test queried the name cell in a way that breaks
> when it becomes a link, update that test minimally to find the name via its link
> role/text. Show the change in the commit.

- [ ] **Step 5: Commit**

```bash
git add web/src/routes.tsx web/src/App.tsx web/src/pages/ExperimentList.tsx
git commit -m "feat(ui/web): Runs nav + Results route + ExperimentList results entry"
```

---

## Task 11: Frontend — TraceRunSwitcher sidebar

**Files:**
- Create: `web/src/components/TraceRunSwitcher.tsx`
- Test: `web/tests/TraceRunSwitcher.test.tsx`

- [ ] **Step 1: Write the failing test**

`web/tests/TraceRunSwitcher.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import TraceRunSwitcher from "../src/components/TraceRunSwitcher";
import type { RunSummary } from "../src/api/types";

const rows: RunSummary[] = [
  { condition: "baseline", rep: 0, finished: true, interrupted_reason: null,
    verify_status: "passed", success: true, started_at: "", duration_s: null,
    n_steps: null, n_tool_calls: null, n_test_runs: null, cost: null },
  { condition: "augmented", rep: 0, finished: true, interrupted_reason: null,
    verify_status: "failed", success: false, started_at: "", duration_s: null,
    n_steps: null, n_tool_calls: null, n_test_runs: null, cost: null },
];

test("lists runs grouped, marks current, fires onSelect", async () => {
  const onSelect = vi.fn();
  render(
    <TraceRunSwitcher
      rows={rows}
      current={{ condition: "baseline", rep: 0 }}
      onSelect={onSelect}
    />,
  );
  // both conditions present
  expect(screen.getByText("baseline")).toBeInTheDocument();
  expect(screen.getByText("augmented")).toBeInTheDocument();
  // clicking the other run selects it
  await userEvent.click(screen.getByRole("button", { name: /augmented · rep 0/i }));
  expect(onSelect).toHaveBeenCalledWith("augmented", 0);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- --run tests/TraceRunSwitcher.test.tsx`
Expected: FAIL (component missing).

- [ ] **Step 3: Implement the switcher**

`web/src/components/TraceRunSwitcher.tsx`:
```tsx
import { Stack, Typography, List, ListItemButton, ListItemText, Box } from "@mui/material";
import VerifyStatusChip from "./VerifyStatusChip";
import type { RunSummary } from "../api/types";

interface Props {
  rows: RunSummary[];
  current: { condition: string; rep: number };
  onSelect: (condition: string, rep: number) => void;
}

export default function TraceRunSwitcher({ rows, current, onSelect }: Props) {
  const byCondition = new Map<string, RunSummary[]>();
  for (const r of rows) {
    const arr = byCondition.get(r.condition) ?? [];
    arr.push(r);
    byCondition.set(r.condition, arr);
  }
  return (
    <Box sx={{ width: 240 }}>
      <Typography variant="overline" color="text.secondary">Runs</Typography>
      <Stack spacing={1}>
        {[...byCondition.entries()].map(([cond, reps]) => (
          <Box key={cond}>
            <Typography variant="caption" color="text.secondary">{cond}</Typography>
            <List dense disablePadding>
              {reps.slice().sort((a, b) => a.rep - b.rep).map((r) => {
                const isCurrent = r.condition === current.condition && r.rep === current.rep;
                return (
                  <ListItemButton
                    key={`${r.condition}-${r.rep}`}
                    selected={isCurrent}
                    onClick={() => onSelect(r.condition, r.rep)}
                    aria-label={`${r.condition} · rep ${r.rep}`}
                  >
                    <ListItemText primary={`${r.condition} · rep ${r.rep}`} />
                    <VerifyStatusChip status={r.verify_status} />
                  </ListItemButton>
                );
              })}
            </List>
          </Box>
        ))}
      </Stack>
    </Box>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- --run tests/TraceRunSwitcher.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/TraceRunSwitcher.tsx web/tests/TraceRunSwitcher.test.tsx
git commit -m "feat(ui/web): TraceRunSwitcher sidebar"
```

---

## Task 12: Frontend — airier TurnCard

**Files:**
- Modify: `web/src/components/TurnCard.tsx`
- Test: `web/tests/TurnCard.test.tsx` (existing — keep passing; add a collapse assertion)

Per spec §"airier turn timeline": clear header (`turn N · role · reason chip`), spacing
between parts, per-role icon+accent, long reasoning/text collapsible, muted stats footer,
and content opts into selection via `selectable`.

- [ ] **Step 1: Update the existing test to assert the airier structure**

In `web/tests/TurnCard.test.tsx`, keep the existing render + assertions and ADD a
collapse check at the end of the test body (after the raw-events assertion):
```tsx
  // Long reasoning is collapsible: a "show more" control appears for long text.
  // (Short fixture text stays inline; assert the role marker is present.)
  expect(screen.getByText(/💭/)).toBeInTheDocument();
```
(Do not change the other assertions; the redesign keeps the reasoning text, the
tool-call, the per-turn stats, and the raw toggle.)

- [ ] **Step 2: Run the test to see current state**

Run: `npm test -- --run tests/TurnCard.test.tsx`
Expected: the new `💭` assertion may PASS already (reasoning is rendered with 💭).
Proceed regardless — the redesign must keep all assertions green.

- [ ] **Step 3: Rewrite `TurnCard` (airier)**

Replace `web/src/components/TurnCard.tsx` with:
```tsx
import { useState } from "react";
import { Card, CardContent, Stack, Typography, Chip, Box, Button } from "@mui/material";
import ToolCallBlock from "./ToolCallBlock";
import RawEventsToggle from "./RawEventsToggle";
import { formatTokens } from "../lib/formatTokens";
import { selectable } from "../theme";
import type { TurnInfo } from "../api/types";
import type { TurnGroup } from "../lib/groupEventsByTurn";

interface Props {
  turn: TurnInfo;
  group: TurnGroup;
  index: number;
  rawEvents: unknown[];
}

const COLLAPSE_CHARS = 600;

// One role marker (icon + theme-aware accent) per part type, for fast scanning.
function roleAccent(type: string): string {
  if (type === "reasoning") return "info.main";
  if (type === "tool-call") return "primary.main";
  if (type === "tool-result") return "success.main";
  if (type === "error") return "error.main";
  return "text.primary";
}

function Collapsible({ text, icon, accent }: { text: string; icon: string; accent: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > COLLAPSE_CHARS;
  const shown = open || !long ? text : text.slice(0, COLLAPSE_CHARS) + "…";
  return (
    <Box sx={{ borderLeft: 2, borderColor: accent, pl: 1.5, py: 0.25 }}>
      <Typography variant="body2" sx={{ whiteSpace: "pre-wrap", ...selectable }}>
        {icon} {shown}
      </Typography>
      {long && (
        <Button size="small" onClick={() => setOpen(!open)} sx={{ mt: 0.25 }}>
          {open ? "show less" : "show more"}
        </Button>
      )}
    </Box>
  );
}

export default function TurnCard({ turn, group, index, rawEvents }: Props) {
  const calls = group.parts.filter((p) => p.type === "tool-call");
  const results = group.parts.filter((p) => p.type === "tool-result");
  const reads = calls.filter((c) => c.name === "read").length;
  const greps = calls.filter((c) => c.name === "grep" || c.name === "search").length;
  const edits = calls.filter((c) => c.name === "edit" || c.name === "write").length;
  const duration = turn.started_at != null && turn.ended_at != null
    ? (turn.ended_at - turn.started_at).toFixed(1) + "s"
    : "—";

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
          <Chip size="small" variant="outlined" label={`turn ${index + 1}`} />
          {turn.reason && <Chip size="small" color="primary" label={turn.reason} />}
          <Box sx={{ flexGrow: 1 }} />
          <Typography variant="caption" color="text.secondary">
            {formatTokens(turn.tokens_in)}/{formatTokens(turn.tokens_out)} tok · ${turn.cost?.toFixed(4) ?? "—"} · {duration}
          </Typography>
        </Stack>

        <Stack spacing={1.25}>
          {group.parts.map((p, i) => {
            if (p.type === "reasoning") {
              return <Collapsible key={i} icon="💭" accent={roleAccent("reasoning")} text={String(p.text ?? "")} />;
            }
            if (p.type === "tool-call") {
              const matched = results.find((r) => r.toolCallID === p.toolCallID || r.callID === p.callID);
              return <ToolCallBlock key={i} call={p} result={matched} />;
            }
            if (p.type === "text") {
              return <Collapsible key={i} icon="🗨" accent={roleAccent("text")} text={String(p.text ?? "")} />;
            }
            return null;
          })}
        </Stack>

        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1.5 }}>
          tools {calls.length} · reads {reads} · greps {greps} · edits {edits}
        </Typography>
        <RawEventsToggle events={rawEvents} />
      </CardContent>
    </Card>
  );
}
```
Notes: the reasoning/text `💭`/`🗨` markers are kept (the test asserts `💭`); the
header now shows `turn N` + reason chip + per-turn token/cost/duration; long
reasoning/text collapse at 600 chars; content is `selectable`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm test -- --run tests/TurnCard.test.tsx`
Expected: PASS (all existing assertions + the `💭` marker).

- [ ] **Step 5: Typecheck**

Run: `npx tsc -b` → clean.

- [ ] **Step 6: Commit**

```bash
git add web/src/components/TurnCard.tsx web/tests/TurnCard.test.tsx
git commit -m "feat(ui/web): airier TurnCard (role markers, collapsible, header stats)"
```

---

## Task 13: Frontend — TraceView with switcher sidebar + selectable content

**Files:**
- Modify: `web/src/pages/TraceView.tsx`

- [ ] **Step 1: Rewrite TraceView to a two-column layout with the switcher**

Replace `web/src/pages/TraceView.tsx` with:
```tsx
import { useNavigate, useParams } from "react-router-dom";
import { Stack, Typography, CircularProgress, Alert, Box } from "@mui/material";
import { useTrace, useEvents, useRuns } from "../api/queries";
import { groupEventsByTurn } from "../lib/groupEventsByTurn";
import VerdictBanner from "../components/VerdictBanner";
import AggregateStatsBar from "../components/AggregateStatsBar";
import TurnCard from "../components/TurnCard";
import VerifyCard from "../components/VerifyCard";
import FinalDiffCard from "../components/FinalDiffCard";
import MethodComparisonCard from "../components/MethodComparisonCard";
import MetricsDrawer from "../components/MetricsDrawer";
import TraceRunSwitcher from "../components/TraceRunSwitcher";

export default function TraceView() {
  const { name, condition, rep } = useParams<{ name: string; condition: string; rep: string }>();
  const navigate = useNavigate();
  const repN = Number(rep);
  const trace = useTrace(name!, condition!, repN);
  const events = useEvents(name!, condition!, repN);
  const runs = useRuns(name);

  if (trace.isLoading) return <CircularProgress />;
  if (trace.error || !trace.data) return <Alert severity="error">Failed to load trace.</Alert>;

  const groups = events.data ? groupEventsByTurn(events.data) : [];

  return (
    <Stack direction="row" spacing={3} sx={{ maxWidth: 1280, mx: "auto", alignItems: "flex-start" }}>
      <Box sx={{ position: "sticky", top: 0, alignSelf: "flex-start", flexShrink: 0 }}>
        {runs.data && (
          <TraceRunSwitcher
            rows={runs.data}
            current={{ condition: condition!, rep: repN }}
            onSelect={(c, r) => navigate(`/runs/${name}/${c}/${r}`)}
          />
        )}
      </Box>

      <Stack spacing={2} sx={{ flex: 1, minWidth: 0 }}>
        <Typography variant="h5">{name} / {condition} / rep {repN}</Typography>
        <VerdictBanner trace={trace.data} />
        <AggregateStatsBar turns={trace.data.turns} />
        {trace.data.turns.map((t, i) => {
          const g = groups.find((gg) => gg.messageId === t.message_id);
          if (!g) return null;
          const raw = events.data?.filter((e: any) => e?.part?.messageID === t.message_id) ?? [];
          return <TurnCard key={t.message_id} turn={t} group={g} index={i} rawEvents={raw} />;
        })}
        <VerifyCard trace={trace.data} />
        <FinalDiffCard name={name!} condition={condition!} rep={repN} />
        <MethodComparisonCard name={name!} condition={condition!} rep={repN} />
        <MetricsDrawer name={name!} condition={condition!} rep={repN} />
      </Stack>
    </Stack>
  );
}
```
Notes: the `FooterNav` import/usage is removed (the sidebar replaces it). `useRuns`
feeds the switcher; selecting a run navigates to its trace.

- [ ] **Step 2: Confirm FooterNav is now unused (leave the file, it's harmless)**

`FooterNav.tsx` is no longer imported. Leave it in place (no test depends on its
mount). Do not delete — out of scope.

- [ ] **Step 3: Run the full frontend suite + typecheck**

Run: `npm test -- --run`
Expected: all green.
Run: `npx tsc -b` → clean.

- [ ] **Step 4: Commit**

```bash
git add web/src/pages/TraceView.tsx
git commit -m "feat(ui/web): TraceView two-column layout with run switcher"
```

---

## Task 14: Apply `selectable` to remaining content surfaces

**Files:**
- Modify: `web/src/components/EventStream.tsx`
- Modify: `web/src/components/RawEventsToggle.tsx`
- Modify: `web/src/components/FinalDiffCard.tsx`
- Modify: `web/src/components/MethodComparisonCard.tsx`
- Modify: `web/src/components/VerifyCard.tsx`

The theme now sets `user-select: none` on the body. These surfaces hold content the
user copies (code, diff, trace output, JSON, failing test names) and must opt back in.

- [ ] **Step 1: EventStream — make the terminal pane selectable**

In `web/src/components/EventStream.tsx`, on the dark output `<Box>` (the one with
`bgcolor: "#0e1116"`), add `userSelect: "text"` to its `sx`:
```tsx
      <Box sx={{
        flex: 1, overflow: "auto", fontFamily: "monospace", fontSize: 13,
        bgcolor: "#0e1116", color: "#dbe1ec", borderRadius: 1, p: 1.5,
        userSelect: "text",
      }}>
```

- [ ] **Step 2: RawEventsToggle — selectable JSON box**

In `web/src/components/RawEventsToggle.tsx`, on the dark `<Box>` holding the JSON
(the one with `bgcolor: "#0e1116"`), add `userSelect: "text"` to its `sx`.

- [ ] **Step 3: FinalDiffCard — selectable hunk lines**

In `web/src/components/FinalDiffCard.tsx`, in the `HunkLine` `<Box sx={{ ... }}>`,
add `userSelect: "text"` to the `sx` object.

- [ ] **Step 4: MethodComparisonCard — selectable code panes**

In `web/src/components/MethodComparisonCard.tsx`, on BOTH `<Box component="pre" ...>`
panes, add `userSelect: "text"` to the `sx`.

- [ ] **Step 5: VerifyCard — selectable failing-test names**

In `web/src/components/VerifyCard.tsx`, on the `<Box sx={{ mt: 1, fontFamily: "monospace", fontSize: 12 }}>`
wrapping the failed names, add `userSelect: "text"`.

- [ ] **Step 6: Run the full frontend suite + typecheck**

Run: `npm test -- --run` → all green.
Run: `npx tsc -b` → clean.

- [ ] **Step 7: Commit**

```bash
git add web/src/components/EventStream.tsx web/src/components/RawEventsToggle.tsx \
        web/src/components/FinalDiffCard.tsx web/src/components/MethodComparisonCard.tsx \
        web/src/components/VerifyCard.tsx
git commit -m "feat(ui/web): opt content surfaces back into text selection"
```

---

## Task 15: Integration — build, full suites, manual smoke

**Files:** none (verification + smoke)

- [ ] **Step 1: Full frontend suite + typecheck + production build**

Run (from `web/`):
```bash
npm test -- --run
npx tsc -b
npm run build
```
Expected: all tests green; tsc clean; build writes `abench_ui/static/`.

- [ ] **Step 2: Full Python suite**

Run: `.venv/bin/pytest -q`
Expected: all green.

- [ ] **Step 3: Boot + endpoint smoke**

```bash
.venv/bin/abench-ui --experiments-dir experiments --port 8802 &
sleep 4
curl -s -o /dev/null -w "root %{http_code}\n" http://127.0.0.1:8802/
curl -s -o /dev/null -w "runs-index %{http_code}\n" http://127.0.0.1:8802/runs
curl -s -w " [summary %{http_code}]\n" "http://127.0.0.1:8802/api/runs/picocli-putValue/summary" || true
kill %1
```
Expected: `root 200`, `runs-index 200` (SPA fallback), and the summary endpoint
returns 200 (with data) or 404 (if picocli-putValue has no runs) — both acceptable;
it must not 500.

- [ ] **Step 4: Manual browser smoke (human)**

Open `http://127.0.0.1:8765` after a normal `abench-ui` boot and confirm:
- Top nav shows **Experiments · Runs** and the theme toggle; nothing is blue.
- From Experiments: clicking an experiment **name** opens its Results (not Edit);
  the `📊` action also opens Results; `✎` still opens Edit.
- Results page: aggregate baseline-vs-augmented table on top (deltas green/red),
  per-run table below; clicking a run row opens its trace.
- TraceView: left run-switcher lists all runs, current highlighted, clicking another
  switches without leaving the page; turn cards are airier (role markers, collapsible
  long text, header token/cost/duration).
- Selecting static labels/headers does nothing (no I-beam); code/diff/trace output
  and metric numbers ARE selectable/copyable.
- Toggle light/dark: all text legible in both; buttons are clearly buttons (solid
  neutral-dark fill); the live-run event stream remains readable.

  (If you cannot run a browser, say so explicitly — do not claim visual success.)

- [ ] **Step 5: Final commit (if any smoke fixes were needed)**

```bash
git add -A
git commit -m "fix(ui/web): UX redesign smoke fixes"
```
(Skip if nothing changed.)

---

## Self-review notes (for the executor)

- Route order in Task 10 matters: `runs/:name` is registered AFTER `runs/sessions/:sid`
  so a literal `/runs/sessions/...` still hits the live Run page, and BEFORE
  `runs/:name/:condition/:rep` (different segment counts, but keep the order).
- `selectable` (Task 4) must reach every content surface (Tasks 6, 7, 12, 14) or that
  content becomes uncopyable under the body's `user-select: none`. The grep
  `grep -rn "0e1116\|component=\"pre\"\|monospace" web/src` finds the panes.
- Types are consistent: `RunSummary` (Task 5) is consumed by RunsTable (7) and
  TraceRunSwitcher (11); `RunsSummary`/`ConditionSummary` (Task 5) by SummaryTable (6)
  and ExperimentResults (8); the backend `summary_json` shape (Task 1) is mirrored by
  `RunsSummary` exactly (`conditions[].metrics[key].{mean,median}`, `deltas`,
  `total_runs`, `valid_runs`).
- `success_rate` on the backend is `0..1`; the UI currently shows per-run `success`
  ticks, not the rate — `success_rate` is carried in the type for future use (not
  surfaced in v1; acceptable).
