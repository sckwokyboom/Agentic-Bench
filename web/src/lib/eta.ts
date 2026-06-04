import type { Envelope } from "../ws/envelope";

const mean = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length;

export interface ExperimentEstimate {
  /** idle: no session yet · estimating: running but no finished run to learn
   *  from · ready: have data · done: session finished. */
  state: "idle" | "estimating" | "ready" | "done";
  totalRuns: number;
  doneRuns: number;
  /** Remaining seconds (null until we have a finished-run duration). */
  etaSeconds: number | null;
  /** Projected total seconds for the whole experiment (null until we can). */
  totalSeconds: number | null;
}

/**
 * Estimate experiment time from the durations of finished runs.
 *
 * Heuristic: average finished-run duration *per condition* (so baseline vs
 * augmented are weighted on their own data; conditions with no data yet fall
 * back to the global average), times the runs still to go. The in-flight run is
 * counted at full expected duration so the number is stable and only steps down
 * as runs complete. `totalSeconds` blends measured done-time with the projected
 * remainder. Wall-clock ≈ this under sequential execution (plus build/verify
 * overhead).
 */
export function estimateExperiment(envelopes: Envelope[]): ExperimentEstimate {
  let totalRuns = 0;
  let conditions: string[] = [];
  let sessionFinished = false;
  let doneRuns = 0;
  const allDurs: number[] = [];
  const durByCond = new Map<string, number[]>();
  const finishedByCond = new Map<string, number>();

  for (const e of envelopes) {
    if (e.type === "session.started") {
      totalRuns = e.total_runs;
      conditions = e.conditions;
    } else if (e.type === "run.finished") {
      doneRuns += 1;
      finishedByCond.set(e.condition, (finishedByCond.get(e.condition) ?? 0) + 1);
      const d = e.duration_s;
      if (typeof d === "number" && d > 0) {
        allDurs.push(d);
        const bucket = durByCond.get(e.condition);
        if (bucket) bucket.push(d);
        else durByCond.set(e.condition, [d]);
      }
    } else if (e.type === "session.finished") {
      sessionFinished = true;
    }
  }

  if (sessionFinished) {
    return {
      state: "done", totalRuns, doneRuns,
      etaSeconds: 0,
      totalSeconds: allDurs.length ? allDurs.reduce((a, b) => a + b, 0) : null,
    };
  }
  if (totalRuns === 0 || conditions.length === 0) {
    return { state: "idle", totalRuns, doneRuns, etaSeconds: null, totalSeconds: null };
  }
  if (allDurs.length === 0) {
    return { state: "estimating", totalRuns, doneRuns, etaSeconds: null, totalSeconds: null };
  }

  const globalAvg = mean(allDurs);
  const repsPerCond = Math.max(1, Math.round(totalRuns / conditions.length));
  let eta = 0;
  for (const c of conditions) {
    const remaining = Math.max(0, repsPerCond - (finishedByCond.get(c) ?? 0));
    const bucket = durByCond.get(c);
    const avg = bucket && bucket.length > 0 ? mean(bucket) : globalAvg;
    eta += remaining * avg;
  }
  const doneTime = allDurs.reduce((a, b) => a + b, 0);
  return {
    state: "ready", totalRuns, doneRuns,
    etaSeconds: eta,
    totalSeconds: doneTime + eta,
  };
}

/** Remaining seconds, or null until estimable / 0 when finished. Thin wrapper
 *  kept for the existing call sites. */
export function estimateEtaSeconds(envelopes: Envelope[]): number | null {
  return estimateExperiment(envelopes).etaSeconds;
}

/**
 * Pre-run estimate from a prior batch's run durations: project the average
 * finished-run duration across all the batch's runs. Returns null when there's
 * nothing usable to learn from.
 */
export function priorEstimateFromRuns(
  runs: { duration_s: number | null }[] | undefined,
): { totalSeconds: number; n: number } | null {
  if (!runs || runs.length === 0) return null;
  const durs = runs
    .map((r) => r.duration_s)
    .filter((d): d is number => typeof d === "number" && d > 0);
  if (durs.length === 0) return null;
  return { totalSeconds: mean(durs) * runs.length, n: runs.length };
}

/** Compact human label, e.g. "~45s", "~6m", "~1h 20m". */
export function formatEta(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `~${s}s`;
  const m = Math.round(s / 60);
  if (m < 60) return `~${m}m`;
  const h = Math.floor(m / 60);
  const rem = m % 60;
  return rem > 0 ? `~${h}h ${rem}m` : `~${h}h`;
}
