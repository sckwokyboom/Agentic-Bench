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

test("scopes to the current run — past runs' events don't mix in", () => {
  const envelopes: Envelope[] = [
    // run 1 — must NOT appear once run 2 is live (no mixing, honest turn counter)
    { type: "raw_event", session_id: "S", event_id: 1, run_idx: 1, condition: "a", rep: 0,
      event: { part: { type: "reasoning", messageID: "M1", text: "OLD-RUN-ONE" }, timestamp: 1 } },
    // run 2 — the current run
    { type: "raw_event", session_id: "S", event_id: 2, run_idx: 2, condition: "b", rep: 1,
      event: { part: { type: "reasoning", messageID: "M2", text: "CURRENT-RUN-TWO" }, timestamp: 2 } },
  ];
  render(<EventStream envelopes={envelopes} />);
  expect(screen.getByText(/CURRENT-RUN-TWO/)).toBeInTheDocument();
  expect(screen.queryByText(/OLD-RUN-ONE/)).toBeNull();              // not mixed in
  expect(screen.getByText(/showing run 2 · b · rep 1/)).toBeInTheDocument();
  // honest counter: the current run starts at turn 1, not turn 2
  expect(screen.getByText(/turn 1/)).toBeInTheDocument();
});

test("renders phase dividers and controller actions in the live stream", () => {
  const envelopes: Envelope[] = [
    { type: "raw_event", session_id: "S", event_id: 1, run_idx: 1, condition: "phased", rep: 0,
      event: { type: "phase.start", phase: "understand" } },
    { type: "raw_event", session_id: "S", event_id: 2, run_idx: 1, condition: "phased", rep: 0,
      event: { part: { type: "reasoning", messageID: "M0", text: "studying putValue" } } },
    { type: "raw_event", session_id: "S", event_id: 3, run_idx: 1, condition: "phased", rep: 0,
      event: { type: "controller", phase: "implement", text: "round 1 reverted (no improvement)" } },
  ];
  render(<EventStream envelopes={envelopes} />);
  expect(screen.getByText("1 · understand")).toBeInTheDocument();     // phase divider
  expect(screen.getByText(/studying putValue/)).toBeInTheDocument();  // agent turn
  expect(screen.getByText("controller")).toBeInTheDocument();         // controller chip
  expect(screen.getByText(/round 1 reverted/)).toBeInTheDocument();   // controller action text
});
