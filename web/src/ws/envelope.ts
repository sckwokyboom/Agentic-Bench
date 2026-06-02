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
  | RunStarted
  | RawEvent
  | RunFinished
  | SessionError
  | SessionFinished;
