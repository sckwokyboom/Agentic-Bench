import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, it, expect, vi } from "vitest";
import ResultsExportButton from "../src/components/ResultsExportButton";
import type { RunsSummary, RunSummary } from "../src/api/types";

const writeText = vi.fn().mockResolvedValue(undefined);
beforeEach(() => {
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText }, configurable: true,
  });
  writeText.mockClear();
});

const summary: RunsSummary = {
  total_runs: 1, valid_runs: 1, deltas: {},
  conditions: [{ name: "baseline", runs: 1, success_rate: 1, metrics: { n_steps: { mean: 5, median: 5 } } }],
};
const runs: RunSummary[] = [{
  condition: "baseline", rep: 0, finished: true, interrupted_reason: null,
  verify_status: "passed", success: true, started_at: "t",
  duration_s: 10, n_steps: 5, n_tool_calls: 2, n_test_runs: 1, cost: 0.01,
}];

describe("ResultsExportButton", () => {
  it("is disabled when there is no data", () => {
    render(<ResultsExportButton experimentName="e" summary={undefined} runs={[]} />);
    expect(screen.getByRole("button", { name: /export results/i })).toBeDisabled();
  });

  it("copies Markdown to the clipboard", async () => {
    render(<ResultsExportButton experimentName="exp-x" batchLabel="latest" summary={summary} runs={runs} />);
    await userEvent.click(screen.getByRole("button", { name: /export results/i }));
    await userEvent.click(screen.getByText("Copy as Markdown"));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const text = writeText.mock.calls[0]![0] as string;
    expect(text).toContain("# Results — exp-x · batch latest");
    expect(text).toContain("## Runs (1)");
    await waitFor(() =>
      expect(screen.getByText(/Markdown copied to clipboard/i)).toBeInTheDocument(),
    );
  });

  it("copies CSV to the clipboard", async () => {
    render(<ResultsExportButton experimentName="exp-x" summary={summary} runs={runs} />);
    await userEvent.click(screen.getByRole("button", { name: /export results/i }));
    await userEvent.click(screen.getByText("Copy runs as CSV"));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const text = writeText.mock.calls[0]![0] as string;
    expect(text.split("\n")[0]).toContain("condition,rep,verify");
  });
});
