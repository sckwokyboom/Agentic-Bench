import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import TurnCard from "../src/components/TurnCard";
import type { UiTurn } from "../src/lib/traceModel";

const turn: UiTurn = {
  index: 0, messageId: "M0", reason: "tool-calls",
  tokensIn: 11700, tokensOut: 118, tokensReasoning: 5, cost: 0.0017, durationS: 62,
  parts: [
    { kind: "reasoning", text: "thinking about it" },
    { kind: "tool", name: "read", args: { path: "a.py" }, output: "file body", exitCode: 0, ok: true },
    { kind: "tool", name: "grep", args: { pattern: "foo" }, output: "match", exitCode: 0, ok: true },
    { kind: "edit", path: "a.py", patch: "@@\n-x\n+y\n" },
  ],
};

// JSX renders the success icon + tool name inside one <b>; the icon is an SVG
// (no text), so match on the bold element's textContent for the tool name.
const bWithText = (want: string) => (_content: string, el: Element | null) =>
  el?.tagName.toLowerCase() === "b" && el.textContent === want;

test("renders tool calls with name+args+result, edits, and a real-name breakdown", async () => {
  const { container } = render(
    <TurnCard turn={turn} index={0} rawEvents={[{ part: { type: "tool" } }]} />,
  );
  expect(screen.getByText(/turn 1/)).toBeInTheDocument();
  expect(screen.getByText(bWithText("read"))).toBeInTheDocument();
  expect(screen.getByText(bWithText("grep"))).toBeInTheDocument();
  // both successful tool calls carry the success CheckCircle icon
  expect(container.querySelectorAll('[data-testid="CheckCircleIcon"]').length).toBe(2);
  // the edit part shows its path + the EditNote icon
  expect(screen.getByText(bWithText("a.py"))).toBeInTheDocument();
  expect(container.querySelector('[data-testid="EditNoteIcon"]')).not.toBeNull();
  // the reasoning part shows the Psychology icon
  expect(container.querySelector('[data-testid="PsychologyOutlinedIcon"]')).not.toBeNull();
  expect(screen.getByText(/read ×1 · grep ×1 · edit ×1/)).toBeInTheDocument();
  expect(screen.getByText(/in 11\.7k · out 118/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /show raw/i }));
  expect(screen.getByText(/"type":"tool"/)).toBeInTheDocument();
});
