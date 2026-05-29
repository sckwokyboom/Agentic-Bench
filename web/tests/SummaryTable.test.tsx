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
  expect(screen.getByText(/baseline/)).toBeInTheDocument();
  expect(screen.getByText(/augmented/)).toBeInTheDocument();
  expect(screen.getByText("steps")).toBeInTheDocument();
  expect(screen.getByText("success rate")).toBeInTheDocument();
  expect(screen.getAllByText("100%")).toHaveLength(2); // one per condition
  expect(screen.getByText("15.00")).toBeInTheDocument();
  expect(screen.getByText("6.00")).toBeInTheDocument();
  expect(screen.getByText("-60.0%")).toBeInTheDocument();
});

test("shows an empty-state when no valid runs", () => {
  render(<SummaryTable summary={{ conditions: [], deltas: {}, total_runs: 0, valid_runs: 0 }} />);
  expect(screen.getByText(/no aggregate/i)).toBeInTheDocument();
});
