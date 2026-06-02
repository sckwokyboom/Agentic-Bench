import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import RunSidebar from "../src/components/RunSidebar";
import type { Envelope } from "../src/ws/envelope";

const navigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>(
    "react-router-dom",
  );
  return { ...actual, useNavigate: () => navigate };
});

beforeEach(() => navigate.mockReset());

function renderSidebar(node: React.ReactElement) {
  return render(<MemoryRouter>{node}</MemoryRouter>);
}

test("seeds pending cards and transitions on run.started + run.finished", () => {
  const envelopes: Envelope[] = [
    { type: "session.started", session_id: "S", event_id: 1, total_runs: 4, conditions: ["a", "b"] },
    { type: "run.started", session_id: "S", event_id: 2, run_idx: 1, total_runs: 4, condition: "a", rep: 0 },
    { type: "run.finished", session_id: "S", event_id: 3, run_idx: 1, total_runs: 4,
      condition: "a", rep: 0, finished: true, interrupted_reason: null,
      verify: { status: "passed", passed_count: 3, failed_count: 0, failed_names: [], command: "pytest", duration_s: 1.2 } },
  ];
  renderSidebar(<RunSidebar conditions={["a", "b"]} totalReps={2} envelopes={envelopes} />);
  expect(screen.getAllByText(/rep \d/)).toHaveLength(4);
  expect(screen.getByText(/3\/3/)).toBeInTheDocument();
});

test("a done card navigates to the trace with ?batch when clicked", () => {
  const envelopes: Envelope[] = [
    { type: "session.started", session_id: "S", event_id: 1, total_runs: 2, conditions: ["a"] },
    { type: "run.started", session_id: "S", event_id: 2, run_idx: 1, total_runs: 2, condition: "a", rep: 0 },
    { type: "run.finished", session_id: "S", event_id: 3, run_idx: 1, total_runs: 2,
      condition: "a", rep: 0, finished: true, interrupted_reason: null,
      verify: { status: "passed", passed_count: 1, failed_count: 0, failed_names: [], command: "pytest", duration_s: 1 } },
  ];
  renderSidebar(
    <RunSidebar
      conditions={["a"]}
      totalReps={2}
      envelopes={envelopes}
      experimentName="exp1"
      batchId="20260602-120000"
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /open trace/i }));
  expect(navigate).toHaveBeenCalledWith(
    "/runs/exp1/a/0?batch=20260602-120000",
  );
});

test("a pending card is not clickable", () => {
  const envelopes: Envelope[] = [
    { type: "session.started", session_id: "S", event_id: 1, total_runs: 2, conditions: ["a"] },
  ];
  renderSidebar(
    <RunSidebar
      conditions={["a"]}
      totalReps={2}
      envelopes={envelopes}
      experimentName="exp1"
      batchId="20260602-120000"
    />,
  );
  expect(screen.queryByRole("button", { name: /open trace/i })).toBeNull();
});
