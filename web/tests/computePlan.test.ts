import { computePlan } from "../src/lib/computePlan";

test("N conditions × M reps = N*M runs", () => {
  const p = computePlan({
    conditions: [{ name: "baseline" }, { name: "augmented" }],
    reps_per_condition: 3,
    timeout_s: 60,
  });
  expect(p.total_runs).toBe(6);
  expect(p.eta_seconds).toBe(6 * 60);
});

test("empty conditions → zero runs", () => {
  const p = computePlan({ conditions: [], reps_per_condition: 5, timeout_s: 10 });
  expect(p.total_runs).toBe(0);
  expect(p.eta_seconds).toBe(0);
});
