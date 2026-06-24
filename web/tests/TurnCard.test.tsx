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
    { kind: "tool", name: "read", args: { path: "a.py" }, output: "file body", outputTokens: 250, exitCode: 0, ok: true },
    { kind: "tool", name: "grep", args: { pattern: "foo" }, output: "match", outputTokens: 30, exitCode: 0, ok: true },
    { kind: "edit", path: "a.py", patch: "@@\n-x\n+y\n" },
  ],
  phase: null, isController: false,
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
  // observation (tool-output) token cost: per-tool label + per-turn total in header
  expect(screen.getByText(/obs ≈280/)).toBeInTheDocument();
  expect(screen.getByText(/≈250 tok ctx/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /show raw/i }));
  expect(screen.getByText(/"type":"tool"/)).toBeInTheDocument();
});

test("renders a controller turn distinctly (chip + phase + action text, no turn/token noise)", () => {
  const ctrlTurn: UiTurn = {
    index: 5, messageId: null, reason: null, tokensIn: null, tokensOut: null,
    tokensReasoning: null, cost: null, durationS: null,
    parts: [{ kind: "controller", text: "round 1 accepted · 84 → 31 failures" }],
    phase: "diagnose", isController: true,
  };
  const { container } = render(<TurnCard turn={ctrlTurn} index={5} rawEvents={[]} />);
  expect(screen.getByText("controller")).toBeInTheDocument();    // chip, not "turn 6"
  expect(screen.getByText("phase: diagnose")).toBeInTheDocument();   // phase chip
  expect(screen.getByText(/round 1 accepted/)).toBeInTheDocument();
  expect(screen.queryByText(/turn 6/)).toBeNull();
  expect(container.querySelector('[data-testid="SettingsOutlinedIcon"]')).not.toBeNull();
});

test("a long edit patch is fully expandable, never hard-truncated", async () => {
  const big = "+line\n".repeat(200);   // 1200 chars > COLLAPSE
  const t: UiTurn = {
    index: 0, messageId: "M0", reason: "stop", tokensIn: 1, tokensOut: 1,
    tokensReasoning: 0, cost: 0, durationS: 1,
    parts: [{ kind: "edit", path: "X.java", patch: big }],
    phase: null, isController: false,
  };
  render(<TurnCard turn={t} index={0} rawEvents={[]} />);
  await userEvent.click(screen.getByRole("button", { name: /show more/i }));
  expect(screen.getByRole("button", { name: /show less/i })).toBeInTheDocument();
});
