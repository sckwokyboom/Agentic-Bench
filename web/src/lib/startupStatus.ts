import type { Envelope } from "../ws/envelope";

/**
 * The "what's happening right now" status shown while the run is starting up
 * but the model has not yet produced any output. Derived purely from the
 * ordered envelope stream so it stays consistent across reconnect/replay.
 */
export interface StartupStatus {
  kind:
    | "baseline_verify"
    | "preparing_workdir"
    | "rate_limit_backoff"
    | "waiting_model"
    | "starting";
  message: string;
  retry?: number;
  maxRetries?: number;
  backoffS?: number;
}

const PHASE_FALLBACK: Record<string, string> = {
  baseline_verify: "Running baseline verification…",
  preparing_workdir: "Preparing an isolated workdir…",
  rate_limit_backoff: "Rate limited — backing off before retrying…",
};

/**
 * Returns the current startup status, or `null` once the model is actively
 * producing output (a raw_event), between runs, or after the session ends.
 *
 * We scan from the end and stop at the first envelope that determines the
 * state: a raw_event means the model is talking (no banner); a run.phase means
 * we're in a known silent setup phase; a run.started with no later raw_event
 * means we're waiting for the model's first response; session.started means the
 * very first moments before any phase has been reported.
 */
export function deriveStartupStatus(envelopes: Envelope[]): StartupStatus | null {
  for (let i = envelopes.length - 1; i >= 0; i -= 1) {
    const e = envelopes[i]!;
    switch (e.type) {
      case "session.finished":
      case "session.error":
      case "raw_event":
      case "run.finished":
        return null;
      case "run.phase":
        return {
          kind: e.phase,
          message: e.message ?? PHASE_FALLBACK[e.phase] ?? "Working…",
          retry: e.retry,
          maxRetries: e.max_retries,
          backoffS: e.backoff_s,
        };
      case "run.started":
        return {
          kind: "waiting_model",
          message: "Waiting for the model's first response…",
        };
      case "session.started":
        return { kind: "starting", message: "Starting the run…" };
      default:
        break;
    }
  }
  return null;
}
