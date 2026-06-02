import { expect, test } from "vitest";
import { turnsFromTrace, turnsFromRawEvents } from "../src/lib/traceModel";
import type { Step } from "../src/api/types";

const steps: Step[] = [
  { kind: "reasoning", ts: 1, turn: 0, text: "thinking" },
  { kind: "tool_call", ts: 2, turn: 0, tool_name: "read", tool_args: { path: "a.py" }, tool_call_id: "c1" },
  { kind: "tool_result", ts: 3, turn: 0, tool_call_id: "c1", output: "file body", exit_code: 0 },
  { kind: "file_edit", ts: 4, turn: 0, path: "a.py", patch: "@@\n-x\n+y\n" },
  { kind: "assistant_text", ts: 5, turn: 1, text: "done" },
];
const turnInfos = [
  { message_id: "M0", reason: "tool-calls", tokens_in: 100, tokens_out: 20, tokens_reasoning: 5, cost: 0.001, started_at: 1, ended_at: 4 },
  { message_id: "M1", reason: "stop", tokens_in: 40, tokens_out: 8, tokens_reasoning: 0, cost: 0.0005, started_at: 5, ended_at: 6 },
];

test("turnsFromTrace groups steps by turn, pairs tool call+result, joins TurnInfo", () => {
  const turns = turnsFromTrace({ steps, turns: turnInfos } as any);
  expect(turns).toHaveLength(2);
  expect(turns[0]!.parts.find((p) => p.kind === "tool")).toMatchObject({
    name: "read", ok: true, output: "file body",
  });
  expect(turns[0]!.parts.some((p) => p.kind === "edit")).toBe(true);
  expect(turns[0]!.reason).toBe("tool-calls");
  expect(turns[0]!.tokensIn).toBe(100);
});

test("turnsFromRawEvents maps the REAL opencode shape", () => {
  const raw = [
    { part: { type: "reasoning", messageID: "M0", text: "thinking" } },
    { part: { type: "tool", messageID: "M0", tool: "read", callID: "c1",
              state: { status: "completed", input: { path: "a.py" }, output: "file body",
                       metadata: { exit: 0 } } } },
    { part: { type: "patch", messageID: "M0", path: "a.py", patch: "@@\n-x\n+y\n" } },
    { part: { type: "step-finish", messageID: "M0", reason: "tool-calls",
              tokens: { input: 100, output: 20, reasoning: 5 }, cost: 0.001 } },
  ];
  const turns = turnsFromRawEvents(raw);
  expect(turns).toHaveLength(1);
  const tool = turns[0]!.parts.find((p) => p.kind === "tool");
  expect(tool).toMatchObject({ name: "read", ok: true, output: "file body" });
  expect(turns[0]!.parts.some((p) => p.kind === "edit")).toBe(true);
  expect(turns[0]!.reason).toBe("tool-calls");
  expect(turns[0]!.tokensIn).toBe(100);
});
