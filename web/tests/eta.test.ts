import { describe, it, expect } from "vitest";
import { estimateEtaSeconds, formatEta } from "../src/lib/eta";
import type { Envelope } from "../src/ws/envelope";

const started = (total: number, conditions: string[]): Envelope => ({
  type: "session.started",
  session_id: "S",
  event_id: 1,
  total_runs: total,
  conditions,
});

let nextId = 100;
const finished = (condition: string, duration_s: number | null): Envelope => ({
  type: "run.finished",
  session_id: "S",
  event_id: nextId++,
  run_idx: 1,
  total_runs: 6,
  condition,
  rep: 0,
  finished: true,
  interrupted_reason: null,
  duration_s,
  verify: {
    status: null, passed_count: 0, failed_count: 0,
    failed_names: [], command: null, duration_s: null,
  },
});

describe("estimateEtaSeconds", () => {
  it("returns null before any run finishes", () => {
    expect(estimateEtaSeconds([started(6, ["baseline", "augmented"])])).toBeNull();
  });

  it("returns null when finished runs carry no usable duration", () => {
    expect(
      estimateEtaSeconds([started(6, ["baseline", "augmented"]), finished("baseline", null)]),
    ).toBeNull();
  });

  it("projects remaining from the global average when a condition has no data", () => {
    // 6 runs over 2 conditions → 3 reps each. One baseline finished at 60s.
    // remaining: baseline 2, augmented 3 (no data → global avg 60) → 5×60 = 300.
    const eta = estimateEtaSeconds([
      started(6, ["baseline", "augmented"]),
      finished("baseline", 60),
    ]);
    expect(eta).toBe(300);
  });

  it("weights each condition by its own average when available", () => {
    // baseline avg 10s (×1), augmented avg 100s (×1). 3 reps each.
    // remaining baseline 2×10=20, augmented 2×100=200 → 220.
    const eta = estimateEtaSeconds([
      started(6, ["baseline", "augmented"]),
      finished("baseline", 10),
      finished("augmented", 100),
    ]);
    expect(eta).toBe(220);
  });

  it("refines (steps down) as more runs of a condition finish", () => {
    const base = [started(6, ["baseline", "augmented"])];
    const after1 = estimateEtaSeconds([...base, finished("baseline", 30)])!;
    const after2 = estimateEtaSeconds([
      ...base,
      finished("baseline", 30),
      finished("baseline", 30),
    ])!;
    expect(after2).toBeLessThan(after1);
  });

  it("returns 0 once the session has finished", () => {
    const eta = estimateEtaSeconds([
      started(6, ["baseline", "augmented"]),
      finished("baseline", 30),
      { type: "session.finished", session_id: "S", event_id: 999, duration_s: 1 },
    ]);
    expect(eta).toBe(0);
  });
});

describe("formatEta", () => {
  it("formats sub-minute, minutes, and hours", () => {
    expect(formatEta(45)).toBe("~45s");
    expect(formatEta(360)).toBe("~6m");
    expect(formatEta(4800)).toBe("~1h 20m");
    expect(formatEta(7200)).toBe("~2h");
  });
});
