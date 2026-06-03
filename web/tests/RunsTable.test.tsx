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
  const { container } = render(<RunsTable rows={rows} onOpen={onOpen} />);
  expect(screen.getByText("baseline")).toBeInTheDocument();
  expect(screen.getByText(/passed/i)).toBeInTheDocument();
  // the success column shows a CheckCircle icon for a successful run (was ✓)
  expect(container.querySelector('[data-testid="CheckCircleIcon"]')).not.toBeNull();
  await userEvent.click(screen.getByText("baseline"));
  expect(onOpen).toHaveBeenCalledWith("baseline", 0);
});

test("empty-state when no runs", () => {
  render(<RunsTable rows={[]} onOpen={() => {}} />);
  expect(screen.getByText(/no runs/i)).toBeInTheDocument();
});

test("shows a service-errors indicator for rows with n_service_errors > 0", () => {
  const erroring: RunSummary[] = [
    { ...rows[0]!, condition: "augmented", n_service_errors: 3 },
  ];
  const { container } = render(<RunsTable rows={erroring} onOpen={() => {}} />);
  // A red ErrorOutline icon flags the run; the count is exposed in its tooltip.
  expect(container.querySelector('[data-testid="ErrorOutlineIcon"]')).not.toBeNull();
});

test("no service-errors indicator when n_service_errors is 0/absent", () => {
  const { container } = render(<RunsTable rows={rows} onOpen={() => {}} />);
  expect(container.querySelector('[data-testid="ErrorOutlineIcon"]')).toBeNull();
});
