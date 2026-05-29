import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import TurnCard from "../src/components/TurnCard";
import type { TurnInfo } from "../src/api/types";
import type { TurnGroup } from "../src/lib/groupEventsByTurn";

const turn: TurnInfo = {
  message_id: "M1", reason: "tool-calls",
  tokens_in: 100, tokens_out: 50, tokens_reasoning: null,
  cost: 0.001, started_at: 0, ended_at: 2,
};
const group: TurnGroup = {
  messageId: "M1",
  parts: [
    { type: "reasoning", text: "thinking…" },
    { type: "tool-call", name: "read", input: { path: "a.py" }, toolCallID: "c1" },
    { type: "tool-result", toolCallID: "c1", output: "ok" },
  ],
  reason: "tool-calls", tokensIn: 100, tokensOut: 50, tokensReasoning: null,
  cost: 0.001, startedAt: 0, endedAt: 2,
};

test("renders reasoning + tool call + per-turn stats", async () => {
  render(<TurnCard turn={turn} group={group} index={0} rawEvents={[{ part: { type: "tool-call" } }]} />);
  expect(screen.getByText(/turn 1/)).toBeInTheDocument();
  // Reasoning appears both in the header summary and the body; the 💭 prefix is unique to the body.
  expect(screen.getByText(/💭 thinking…/)).toBeInTheDocument();
  // The tool-call has a matching tool-result, so ToolCallBlock renders the ✓ (success) icon.
  // JSX splits "{icon} {name}" into separate text nodes, so match on the bold element's textContent.
  expect(
    screen.getByText((_content, el) => el?.tagName.toLowerCase() === "b" && el.textContent === "✓ read"),
  ).toBeInTheDocument();
  expect(screen.getByText(/reads 1/)).toBeInTheDocument();
  const btn = screen.getByRole("button", { name: /show raw/i });
  await userEvent.click(btn);
  // The raw JSONL line is unique (the turn reason chip also contains "tool-call").
  expect(screen.getByText(/"type":"tool-call"/)).toBeInTheDocument();
});
