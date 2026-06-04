import type { Envelope } from "../ws/envelope";

const mean = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length;

/**
 * Estimate the remaining experiment time (in seconds) from the durations of
 * runs that have already finished.
 *
 * Heuristic: average finished-run duration *per condition* (so a condition that
 * runs slower with its augmentation is weighted on its own data), falling back
 * to the global average for conditions that have no finished run yet. The
 * in-flight run is counted at full expected duration — we don't subtract its
 * elapsed time — so the number is stable and only steps down as runs complete.
 *
 * Returns `null` while there is not yet enough data (no finished run with a
 * usable duration), and `0` once the session has finished.
 */
export function estimateEtaSeconds(envelopes: Envelope[]): number | null {
  let totalRuns = 0;
  let conditions: string[] = [];
  let sessionFinished = false;
  const allDurs: number[] = [];
  const durByCond = new Map<string, number[]>();
  const finishedByCond = new Map<string, number>();

  for (const e of envelopes) {
    if (e.type === "session.started") {
      totalRuns = e.total_runs;
      conditions = e.conditions;
    } else if (e.type === "run.finished") {
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

  if (sessionFinished) return 0;
  if (allDurs.length === 0 || totalRuns === 0 || conditions.length === 0) {
    return null;
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
  return eta;
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
