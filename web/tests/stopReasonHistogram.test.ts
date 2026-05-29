import { stopReasonHistogram } from "../src/lib/stopReasonHistogram";

test("counts reasons across turns, treats null as 'unknown'", () => {
  const h = stopReasonHistogram([
    { reason: "tool-calls" } as any,
    { reason: "tool-calls" } as any,
    { reason: "stop" } as any,
    { reason: null } as any,
  ]);
  expect(h).toEqual({ "tool-calls": 2, "stop": 1, "unknown": 1 });
});

test("empty turns → empty object", () => {
  expect(stopReasonHistogram([])).toEqual({});
});
