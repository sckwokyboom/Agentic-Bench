import { render, screen } from "@testing-library/react";
import RunSidebar from "../src/components/RunSidebar";
import type { Envelope } from "../src/ws/envelope";

test("seeds pending cards and transitions on run.started + run.finished", () => {
  const envelopes: Envelope[] = [
    { type: "session.started", session_id: "S", event_id: 1, total_runs: 4, conditions: ["a", "b"] },
    { type: "run.started", session_id: "S", event_id: 2, run_idx: 1, total_runs: 4, condition: "a", rep: 0 },
    { type: "run.finished", session_id: "S", event_id: 3, run_idx: 1, total_runs: 4,
      condition: "a", rep: 0, finished: true, interrupted_reason: null,
      verify: { status: "passed", passed_count: 3, failed_count: 0, failed_names: [], command: "pytest", duration_s: 1.2 } },
  ];
  render(<RunSidebar conditions={["a", "b"]} totalReps={2} envelopes={envelopes} />);
  expect(screen.getAllByText(/rep \d/)).toHaveLength(4);
  expect(screen.getByText(/3\/3/)).toBeInTheDocument();
});
