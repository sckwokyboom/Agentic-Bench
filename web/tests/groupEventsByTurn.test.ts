import { groupEventsByTurn } from "../src/lib/groupEventsByTurn";

const events = [
  { part: { type: "step-start", messageID: "M1" }, timestamp: 1 },
  { part: { type: "reasoning", messageID: "M1", text: "thinking" }, timestamp: 2 },
  { part: { type: "tool-call", messageID: "M1", name: "ls" }, timestamp: 3 },
  { part: { type: "step-finish", messageID: "M1", reason: "tool-calls",
            tokens: { input: 10, output: 5 }, cost: 0.01 }, timestamp: 4 },
  { part: { type: "step-start", messageID: "M2" }, timestamp: 5 },
  { part: { type: "text", messageID: "M2", text: "Done" }, timestamp: 6 },
  { part: { type: "step-finish", messageID: "M2", reason: "stop",
            tokens: { input: 12, output: 8 }, cost: 0.02 }, timestamp: 7 },
];

test("groups by messageID, sorts by timestamp, extracts step-finish fields", () => {
  const groups = groupEventsByTurn(events);
  expect(groups).toHaveLength(2);
  expect(groups[0]!.messageId).toBe("M1");
  expect(groups[0]!.reason).toBe("tool-calls");
  expect(groups[0]!.tokensIn).toBe(10);
  expect(groups[1]!.messageId).toBe("M2");
  expect(groups[1]!.reason).toBe("stop");
});

test("turn without step-finish has reason=null", () => {
  const groups = groupEventsByTurn([
    { part: { type: "reasoning", messageID: "X", text: "..." }, timestamp: 1 },
  ]);
  expect(groups).toHaveLength(1);
  expect(groups[0]!.reason).toBeNull();
});
