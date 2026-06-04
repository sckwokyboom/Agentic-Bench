import type { VerifySummary } from "../api/types";

export interface SessionStarted {
  type: "session.started";
  session_id: string;
  event_id: number;
  total_runs: number;
  conditions: string[];
  // Added in the batches feature. The server always sends these now, but they
  // are kept optional so existing constructors (tests/replay) compile unchanged.
  batch_id?: string;
  isolation?: { nonce_prefix: boolean; shuffle_order: boolean };
  model?: string;
}

export interface RunStarted {
  type: "run.started";
  session_id: string;
  event_id: number;
  run_idx: number;
  total_runs: number;
  condition: string;
  rep: number;
}

export interface RawEvent {
  type: "raw_event";
  session_id: string;
  event_id: number;
  run_idx: number;
  condition: string;
  rep: number;
  event: Record<string, unknown>;
}

export interface RunFinished {
  type: "run.finished";
  session_id: string;
  event_id: number;
  run_idx: number;
  total_runs: number;
  condition: string;
  rep: number;
  finished: boolean;
  interrupted_reason: string | null;
  verify: VerifySummary;
  // Added in the batches feature; optional-safe (see SessionStarted).
  batch_id?: string;
  // Validity signals (Tasks A/B); optional-safe for replay/tests.
  n_service_errors?: number;
  made_source_changes?: boolean;
  verify_insensitive?: boolean;
  // Wall-clock seconds the agent ran for this rep; drives the live ETA.
  duration_s?: number | null;
}

export interface RunPhase {
  type: "run.phase";
  session_id: string;
  event_id: number;
  // Fine-grained setup status during the silent startup window. These are the
  // phases the UI cannot otherwise see (no raw events flow yet).
  phase: "baseline_verify" | "preparing_workdir" | "rate_limit_backoff";
  message?: string;
  run_idx?: number;
  condition?: string;
  rep?: number;
  // Present only for rate_limit_backoff.
  retry?: number;
  max_retries?: number;
  backoff_s?: number;
}

export interface SessionError {
  type: "session.error";
  session_id: string;
  event_id: number;
  message: string;
  traceback?: string;
}

export interface SessionFinished {
  type: "session.finished";
  session_id: string;
  event_id: number;
  duration_s: number;
}

export type Envelope =
  | SessionStarted
  | RunPhase
  | RunStarted
  | RawEvent
  | RunFinished
  | SessionError
  | SessionFinished;
