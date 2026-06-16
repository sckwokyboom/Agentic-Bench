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

test("re-verify: verifying on the current row, fresh verdict on done, queued on pending", () => {
  // success: null → no Cancel icon (whose titleAccess="failed" would otherwise
  // collide with the "stale chip replaced" assertion below); we test the verify
  // cell here, not the success column.
  const three: RunSummary[] = [
    { ...rows[0]!, condition: "baseline", verify_status: "failed", success: null },
    { ...rows[0]!, condition: "augmented", verify_status: "failed", success: null },
    { ...rows[0]!, condition: "augmented-tool", verify_status: "failed", success: null },
  ];
  render(
    <RunsTable
      rows={three}
      onOpen={() => {}}
      reverify={{
        current: { condition: "augmented", rep: 0 },
        resultByKey: { "baseline/0": "passed" },
      }}
    />,
  );
  expect(screen.getByText(/verifying/i)).toBeInTheDocument();   // current: augmented
  expect(screen.getByText("passed")).toBeInTheDocument();       // done: baseline (fresh verdict)
  expect(screen.getByText(/queued/i)).toBeInTheDocument();      // pending: augmented-tool
  // the stale "failed" chips are replaced while a re-verify is in flight
  expect(screen.queryByText("failed")).toBeNull();
});

test("re-verify: absent prop keeps the stored verify status (regression)", () => {
  render(<RunsTable rows={rows} onOpen={() => {}} />);
  expect(screen.getByText(/passed/i)).toBeInTheDocument();
  expect(screen.queryByText(/verifying/i)).toBeNull();
  expect(screen.queryByText(/queued/i)).toBeNull();
});
