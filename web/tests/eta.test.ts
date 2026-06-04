import { describe, it, expect } from "vitest";
import {
  estimateEtaSeconds, estimateExperiment, priorEstimateFromRuns, formatEta,
} from "../src/lib/eta";
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

describe("estimateExperiment", () => {
  it("is idle before a session starts", () => {
    expect(estimateExperiment([]).state).toBe("idle");
  });

  it("is 'estimating' once running but before any run finishes", () => {
    const e = estimateExperiment([started(6, ["baseline", "augmented"])]);
    expect(e.state).toBe("estimating");
    expect(e.totalRuns).toBe(6);
    expect(e.etaSeconds).toBeNull();
    expect(e.totalSeconds).toBeNull();
  });

  it("is 'ready' with total = done-time + remaining once a run finishes", () => {
    const e = estimateExperiment([
      started(6, ["baseline", "augmented"]),
      finished("baseline", 60),
    ]);
    expect(e.state).toBe("ready");
    expect(e.doneRuns).toBe(1);
    expect(e.etaSeconds).toBe(300);        // 5 remaining × 60 (global fallback)
    expect(e.totalSeconds).toBe(360);      // 60 done + 300 remaining
  });

  it("is 'done' after session.finished", () => {
    const e = estimateExperiment([
      started(6, ["baseline", "augmented"]),
      finished("baseline", 60),
      { type: "session.finished", session_id: "S", event_id: 9, duration_s: 1 },
    ]);
    expect(e.state).toBe("done");
    expect(e.etaSeconds).toBe(0);
  });
});

describe("priorEstimateFromRuns", () => {
  it("returns null with no usable durations", () => {
    expect(priorEstimateFromRuns(undefined)).toBeNull();
    expect(priorEstimateFromRuns([])).toBeNull();
    expect(priorEstimateFromRuns([{ duration_s: null }])).toBeNull();
  });

  it("projects the average duration across all runs", () => {
    expect(priorEstimateFromRuns([{ duration_s: 10 }, { duration_s: 20 }]))
      .toEqual({ totalSeconds: 30, n: 2 });
    // null durations still count toward n (avg of present × n)
    expect(priorEstimateFromRuns([
      { duration_s: 10 }, { duration_s: null }, { duration_s: 20 },
    ])).toEqual({ totalSeconds: 45, n: 3 });
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
