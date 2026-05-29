import { render, screen } from "@testing-library/react";
import EventStream from "../src/components/EventStream";
import type { Envelope } from "../src/ws/envelope";

test("renders one turn block per messageID", () => {
  const envelopes: Envelope[] = [
    { type: "raw_event", session_id: "S", event_id: 1, run_idx: 1, condition: "a", rep: 0,
      event: { part: { type: "reasoning", messageID: "M1", text: "hello" }, timestamp: 1 } },
    { type: "raw_event", session_id: "S", event_id: 2, run_idx: 1, condition: "a", rep: 0,
      event: { part: { type: "step-finish", messageID: "M1", reason: "stop", tokens: { input: 1, output: 1 } }, timestamp: 2 } },
  ];
  render(<EventStream envelopes={envelopes} />);
  expect(screen.getByText(/turn 1/)).toBeInTheDocument();
  expect(screen.getByText(/hello/)).toBeInTheDocument();
});
