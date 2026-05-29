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
  expect(screen.getByText("baseline")).toBeInTheDocument();
  expect(screen.getByText("augmented")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /augmented · rep 0/i }));
  expect(onSelect).toHaveBeenCalledWith("augmented", 0);
});
