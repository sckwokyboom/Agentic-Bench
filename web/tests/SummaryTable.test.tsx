import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import SummaryTable from "../src/components/SummaryTable";
import type { RunsSummary } from "../src/api/types";

const summary: RunsSummary = {
  total_runs: 4,
  valid_runs: 4,
  conditions: [
    { name: "baseline", runs: 2, success_rate: 1,
      metrics: {
        n_steps: { mean: 15, median: 15 },
        cost: { mean: 0.03, median: 0.03 },
        tokens_in: { mean: 1000, median: 1000 },
        tokens_out: { mean: 500, median: 500 },
        cache_read: { mean: 0, median: 0 },
      } },
    { name: "augmented", runs: 2, success_rate: 1,
      metrics: {
        n_steps: { mean: 6, median: 6 },
        cost: { mean: 0.03, median: 0.03 },
        tokens_in: { mean: 800, median: 800 },
        tokens_out: { mean: 500, median: 500 },
        cache_read: { mean: 0, median: 0 },
      } },
  ],
  deltas: { n_steps: -60, cost: 0, tokens_in: -20, tokens_out: 0, cache_read: -50 },
};

test("renders condition columns, metric means and the delta", () => {
  render(<SummaryTable summary={summary} />);
  expect(screen.getByText(/baseline/)).toBeInTheDocument();
  expect(screen.getByText(/augmented/)).toBeInTheDocument();
  expect(screen.getByText("steps")).toBeInTheDocument();
  expect(screen.getByText("success rate")).toBeInTheDocument();
  expect(screen.getAllByText("100%")).toHaveLength(2); // one per condition
  expect(screen.getByText("15.00")).toBeInTheDocument();
  expect(screen.getByText("6.00")).toBeInTheDocument();
  expect(screen.getByText("-60.0%")).toBeInTheDocument();
});

test("renders the new token rows", () => {
  render(<SummaryTable summary={summary} />);
  expect(screen.getByText("tokens read (in)")).toBeInTheDocument();
  expect(screen.getByText("tokens generated (out)")).toBeInTheDocument();
  expect(screen.getByText("cache read")).toBeInTheDocument();
});

// MUI resolves the sx `color` token to a concrete rgb()/rgba() in jsdom's
// getComputedStyle: success.main → rgb(46,125,50) (green-dominant), error.main →
// rgb(211,47,47) (red-dominant), text.secondary → rgba(0,0,0,0.6) (balanced grey).
function rgb(el: HTMLElement): { r: number; g: number; b: number } {
  const color = getComputedStyle(el).color;
  const m = /rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(color);
  expect(m, `expected an rgb(a) color, got "${color}"`).not.toBeNull();
  return { r: Number(m![1]), g: Number(m![2]), b: Number(m![3]) };
}

// A `lower`-direction metric with a NEGATIVE delta is the desired RAG effect →
// the delta cell must carry the success color (green-dominant), not error/grey.
test("colors a negative lower-is-better delta as success", () => {
  render(<SummaryTable summary={summary} />);
  const { r, g, b } = rgb(screen.getByText("-20.0%")); // tokens_in (lower), Δ -20
  expect(g).toBeGreaterThan(r); // green channel dominates → success
  expect(g).toBeGreaterThan(b);
});

// A `neutral`-direction metric (cache_read) must NEVER be colored success/error,
// even with a non-zero delta — it falls back to the neutral text.secondary token.
test("never colors a neutral metric's delta as success or error", () => {
  render(<SummaryTable summary={summary} />);
  const { r, g, b } = rgb(screen.getByText("-50.0%")); // cache_read (neutral), Δ -50
  const greenDominant = g > r && g > b;
  const redDominant = r > g && r > b;
  expect(greenDominant).toBe(false); // not success
  expect(redDominant).toBe(false); // not error → balanced grey
});

test("shows an empty-state when no valid runs", () => {
  render(<SummaryTable summary={{ conditions: [], deltas: {}, total_runs: 0, valid_runs: 0 }} />);
  expect(screen.getByText(/no aggregate/i)).toBeInTheDocument();
});
