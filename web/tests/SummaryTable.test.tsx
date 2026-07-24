import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import SummaryTable from "../src/components/SummaryTable";
import type { Panel, PanelCondition, PanelMetric } from "../src/api/types";

const m = (
  value: number, ratio: number | null = null,
  ci: [number, number] | null = null,
): PanelMetric => ({ value, ratio, ci, cliffs: null });

function cond(over: Partial<PanelCondition> & { name: string }): PanelCondition {
  return {
    n_valid: 5, n_total: 5,
    pass: { k: 0, n: 5, rate: 0, wilson: null, beta_p_gt_baseline: null },
    tests_pass_rate: 1,
    cost_per_pass: { tokens: null, seconds: null },
    behavior: { tool_calls: 100, read_share: 0.3, search_share: 0.28,
      edit_share: 0.05, bash_share: 0.3, files_edited: 4 },
    flags: { interrupted: 0, crashed: 0 },
    metrics: {},
    verdict: "inconclusive",
    ...over,
  };
}

const panel: Panel = {
  baseline: "baseline", agg: "median", total_runs: 15, valid_runs: 15,
  metric_order: ["duration_s", "n_steps", "n_tool_calls", "tokens_in", "tokens_out", "n_test_runs", "n_tests_executed"],
  conditions: [
    cond({
      name: "baseline", verdict: "baseline",
      pass: { k: 3, n: 5, rate: 0.6, wilson: null, beta_p_gt_baseline: null },
      tests_pass_rate: 1, cost_per_pass: { tokens: 183000, seconds: null },
      metrics: { duration_s: m(1100), n_steps: m(130), n_tool_calls: m(60),
        tokens_in: m(95000), tokens_out: m(110000), n_test_runs: m(9), n_tests_executed: m(2437) },
    }),
    cond({
      name: "augmented", verdict: "promising",
      pass: { k: 4, n: 5, rate: 0.8, wilson: null, beta_p_gt_baseline: 0.7 },
      tests_pass_rate: 1, cost_per_pass: { tokens: 175000, seconds: null },
      behavior: { tool_calls: 100, read_share: 0.26, search_share: 0.18,
        edit_share: 0.07, bash_share: 0.4, files_edited: 6 },
      metrics: {
        duration_s: m(1300, 1.18, [0.92, 1.46]),   // crosses 1 → inconclusive
        n_steps: m(143, 1.1, [0.85, 1.4]),
        n_tool_calls: m(67, 1.12, [0.88, 1.4]),
        tokens_in: m(80000, 0.92, [0.85, 0.96]),    // CI fully < 1 → cheaper (good)
        tokens_out: m(140000, 1.27, [1.06, 1.55]),  // CI fully > 1 → costlier (bad)
        n_test_runs: m(9, 1.0, [0.7, 1.4]),
        n_tests_executed: m(2437, 1.0, [0.95, 1.05]),
      },
    }),
    cond({
      name: "forced", verdict: "dominated",
      pass: { k: 1, n: 5, rate: 0.2, wilson: null, beta_p_gt_baseline: 0.05 },
      tests_pass_rate: 0.972, cost_per_pass: { tokens: 956000, seconds: null },
      behavior: { tool_calls: 100, read_share: 0.14, search_share: 0.1,
        edit_share: 0.23, bash_share: 0.52, files_edited: 38 },
      metrics: {
        duration_s: m(2860, 2.6, [1.5, 4.1]),       // CI fully > 1 → costlier (bad)
        n_steps: m(390, 3.0, [1.8, 4.7]),
        n_tool_calls: m(186, 3.1, [1.9, 4.8]),
        tokens_in: m(257000, 2.7, [1.6, 4.3]),
        tokens_out: m(319000, 2.9, [1.7, 4.6]),
        n_test_runs: m(25, 2.8, [1.6, 4.5]),
        n_tests_executed: m(2326, 0.95, [0.93, 0.99]),  // CI < 1 → fewer tests, cheaper (good)
      },
    }),
  ],
};

const noop = () => {};

function rgb(el: HTMLElement): { r: number; g: number; b: number } {
  const color = getComputedStyle(el).color;
  const x = /rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(color);
  expect(x, `expected an rgb(a) color, got "${color}"`).not.toBeNull();
  return { r: Number(x![1]), g: Number(x![2]), b: Number(x![3]) };
}

test("renders transposed columns: baseline reference + each condition with n", () => {
  render(<SummaryTable panel={panel} agg="median" onAggChange={noop} />);
  expect(screen.getByText(/baseline \(baseline\)/)).toBeInTheDocument();
  expect(screen.getByText("augmented")).toBeInTheDocument();
  expect(screen.getByText("forced")).toBeInTheDocument();
  expect(screen.getAllByText("n = 5").length).toBe(3);
});

test("renders the three sections and verdict pills", () => {
  render(<SummaryTable panel={panel} agg="median" onAggChange={noop} />);
  expect(screen.getByText("summary")).toBeInTheDocument();
  expect(screen.queryByText("outcome")).toBeNull();
  expect(screen.getByText(/cost · ratio vs baseline/)).toBeInTheDocument();
  expect(screen.getByText(/behavior · share of tool calls/)).toBeInTheDocument();
  expect(screen.getByText("promising")).toBeInTheDocument();
  expect(screen.getByText("dominated")).toBeInTheDocument();
  expect(screen.getByText("reference")).toBeInTheDocument();
});

test("pass rate as k / n; tokens/pass formatted; baseline labelled 'baseline'", () => {
  render(<SummaryTable panel={panel} agg="median" onAggChange={noop} />);
  expect(screen.getByText("3 / 5")).toBeInTheDocument();
  expect(screen.getByText("4 / 5")).toBeInTheDocument();
  expect(screen.getByText("1 / 5")).toBeInTheDocument();
  expect(screen.getByText("183k")).toBeInTheDocument();   // baseline tokens/pass
  expect(screen.getByText("956k")).toBeInTheDocument();   // forced tokens/pass
  expect(screen.getAllByText("baseline").length).toBeGreaterThan(0); // cost rows show it
});

test("cost cell shows ratio with [95% CI], leading zero preserved", () => {
  render(<SummaryTable panel={panel} agg="median" onAggChange={noop} />);
  // augmented duration: 1.18× [0.92–1.46] — leading zero, en-dash, brackets.
  expect(screen.getByText("1.18× [0.92–1.46]")).toBeInTheDocument();
  expect(screen.getByText("2.60× [1.50–4.10]")).toBeInTheDocument();
});

test("directional color: CI fully above 1 is bad (red), fully below 1 is good (green), crossing is neutral", () => {
  render(<SummaryTable panel={panel} agg="median" onAggChange={noop} />);
  // forced duration 2.60× [1.50–4.10] → costlier → error (red dominant)
  const bad = rgb(screen.getByText("2.60× [1.50–4.10]"));
  expect(bad.r).toBeGreaterThan(bad.g);
  expect(bad.r).toBeGreaterThan(bad.b);
  // augmented tokens read 0.92× [0.85–0.96] → cheaper → success (green dominant)
  const good = rgb(screen.getByText("0.92× [0.85–0.96]"));
  expect(good.g).toBeGreaterThan(good.r);
  // augmented duration 1.18× [0.92–1.46] → crosses 1 → neutral grey (balanced)
  const neutral = rgb(screen.getByText("1.18× [0.92–1.46]"));
  const greenDom = neutral.g > neutral.r && neutral.g > neutral.b;
  const redDom = neutral.r > neutral.g && neutral.r > neutral.b;
  expect(greenDom).toBe(false);
  expect(redDom).toBe(false);
});

test("tests executed below baseline is green — fewer executions is cheaper", () => {
  render(<SummaryTable panel={panel} agg="median" onAggChange={noop} />);
  // forced tests executed 0.95× [0.93–0.99] → fewer than baseline → success (green)
  const good = rgb(screen.getByText("0.95× [0.93–0.99]"));
  expect(good.g).toBeGreaterThan(good.r);
  expect(good.g).toBeGreaterThan(good.b);
});

test("behavior shares render as percentages", () => {
  render(<SummaryTable panel={panel} agg="median" onAggChange={noop} />);
  expect(screen.getByText("read")).toBeInTheDocument();
  expect(screen.getByText("bash")).toBeInTheDocument();
  expect(screen.getByText("52%")).toBeInTheDocument();   // forced bash share
  expect(screen.getByText("23%")).toBeInTheDocument();   // forced edit share
});

test("aggregate toggle invokes onAggChange", async () => {
  const onAgg = vi.fn();
  render(<SummaryTable panel={panel} agg="median" onAggChange={onAgg} />);
  await userEvent.click(screen.getByRole("button", { name: "mean" }));
  expect(onAgg).toHaveBeenCalledWith("mean");
});

test("points users to the Runs table for include/exclude (no embedded raw table)", () => {
  render(<SummaryTable panel={panel} agg="median" onAggChange={noop} />);
  // The per-run include/exclude control now lives in the unified Runs table, not
  // a duplicate table inside the comparison view.
  expect(screen.queryByText("Raw runs")).toBeNull();
  expect(screen.getByText(/untick a run in the runs table below/i)).toBeInTheDocument();
});

test("empty panel shows an explanatory empty-state", () => {
  const empty: Panel = { baseline: "baseline", agg: "median", total_runs: 0,
    valid_runs: 0, metric_order: [], conditions: [] };
  render(<SummaryTable panel={empty} agg="median" onAggChange={noop} />);
  expect(screen.getByText(/no aggregate yet/i)).toBeInTheDocument();
});
