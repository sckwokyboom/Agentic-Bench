import { expect, test } from "vitest";
import {
  turnsFromTrace, turnsFromRawEvents, estimateTokens,
  observationTokensByTool, observationTokensTotal, formatToolArgs,
} from "../src/lib/traceModel";
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

test("observation token cost: estimate + per-tool aggregation", () => {
  const turns = turnsFromTrace({ steps, turns: turnInfos } as any);
  // read result "file body" = 9 chars → ceil(9/4) = 3 tokens, attributed to read
  expect(observationTokensTotal(turns)).toBe(3);
  expect(observationTokensByTool(turns)).toEqual({ read: 3 });
  expect(estimateTokens("a".repeat(400))).toBe(100);
  expect(estimateTokens(null)).toBe(0);
});

test("turnsFromTrace joins TurnInfo by message_id, not array index (turn without step-finish)", () => {
  const stepsNoFinish: Step[] = [
    { kind: "reasoning", ts: 1, turn: 0, message_id: "MA", text: "a" },   // turn 0, NO step-finish
    { kind: "assistant_text", ts: 2, turn: 1, message_id: "MB", text: "b" }, // turn 1
  ];
  const turns = [
    { message_id: "MB", reason: "stop", tokens_in: 99, tokens_out: 9, tokens_reasoning: 0, cost: 0.002, started_at: 2, ended_at: 3 },
  ];
  const ui = turnsFromTrace({ steps: stepsNoFinish, turns } as any);
  const a = ui.find((t) => t.messageId === "MA")!;
  const b = ui.find((t) => t.messageId === "MB")!;
  expect(a.tokensIn).toBeNull();   // MUST NOT inherit MB's tokens
  expect(b.tokensIn).toBe(99);
});

test("turnsFromTrace tags phases and surfaces controller steps as their own turns", () => {
  const s: Step[] = [
    { kind: "assistant_text", ts: 1, turn: 0, message_id: "M0", text: "contract …", phase: "understand" },
    { kind: "controller", ts: 2, turn: 1, text: "ran suite -> 84 failures in 3 clusters", phase: "implement" },
    { kind: "file_edit", ts: 3, turn: 2, message_id: "M2", path: "X.java", patch: "@@", phase: "implement" },
  ];
  const turns = turnsFromTrace({ steps: s, turns: [] } as any);
  const ctrl = turns.find((t) => t.isController)!;
  expect(ctrl).toBeTruthy();
  expect(ctrl.phase).toBe("implement");
  const cp = ctrl.parts.find((p) => p.kind === "controller") as { kind: "controller"; text: string };
  expect(cp.text).toContain("ran suite");
  const understand = turns.find((t) => t.phase === "understand")!;
  expect(understand.isController).toBe(false);
  expect(understand.parts.some((p) => p.kind === "text")).toBe(true);
});

test("formatToolArgs renders the meaningful input per tool (grep shows the pattern)", () => {
  // the bug: grep used to show `path` and drop `pattern`
  expect(formatToolArgs("grep", { pattern: "putValue", include: "*.java", path: "/tmp/abench-xy/src" }))
    .toBe("putValue  include:*.java in:src");
  expect(formatToolArgs("grep", { pattern: "TextTable" })).toBe("TextTable");
  expect(formatToolArgs("read", { filePath: "/tmp/abench-xy/src/X.java", offset: 17350, limit: 150 }))
    .toBe("src/X.java  @17350+150");
  expect(formatToolArgs("glob", { pattern: "**/*Test.java" })).toBe("**/*Test.java");
  expect(formatToolArgs("bash", { command: "./gradlew test", description: "run" })).toBe("./gradlew test");
  // edit must NEVER dump the huge oldString/newString — just the path
  expect(formatToolArgs("edit", { filePath: "/tmp/abench-xy/A.java", oldString: "x".repeat(999), newString: "y".repeat(999) }))
    .toBe("A.java");
  expect(formatToolArgs("todowrite", { todos: [1, 2, 3] })).toBe("3 todos");
  expect(formatToolArgs("task", { description: "research X", subagent_type: "explore", prompt: "z".repeat(999) }))
    .toBe("research X (explore)");
});

test("turnsFromRawEvents coalesces repeated parts by id (running → completed)", () => {
  const raw = [
    { part: { type: "tool", id: "prt_1", messageID: "M0", tool: "bash", callID: "c1",
              state: { status: "running", input: { command: "go test ./..." } } } },
    { part: { type: "tool", id: "prt_1", messageID: "M0", tool: "bash", callID: "c1",
              state: { status: "completed", input: { command: "go test ./..." },
                       output: "ok", metadata: { exit: 0 } } } },
  ];
  const turns = turnsFromRawEvents(raw);
  expect(turns).toHaveLength(1);
  const tools = turns[0]!.parts.filter((p) => p.kind === "tool");
  expect(tools).toHaveLength(1);                 // not 2
  expect(tools[0]).toMatchObject({ ok: true, output: "ok" });  // finalized state wins
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
