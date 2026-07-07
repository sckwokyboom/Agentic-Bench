import { describe, it, expect } from "vitest";
import { deriveStartupStatus } from "../src/lib/startupStatus";
import type { Envelope } from "../src/ws/envelope";

const sessionStarted: Envelope = {
  type: "session.started",
  session_id: "S",
  event_id: 1,
  total_runs: 2,
  conditions: ["baseline"],
};

const runStarted: Envelope = {
  type: "run.started",
  session_id: "S",
  event_id: 3,
  run_idx: 1,
  total_runs: 2,
  condition: "baseline",
  rep: 0,
};

const rawEvent: Envelope = {
  type: "raw_event",
  session_id: "S",
  event_id: 4,
  run_idx: 1,
  condition: "baseline",
  rep: 0,
  event: { type: "message.start" },
};

describe("deriveStartupStatus", () => {
  it("returns null for an empty stream", () => {
    expect(deriveStartupStatus([])).toBeNull();
  });

  it("reports 'starting' right after session.started", () => {
    const s = deriveStartupStatus([sessionStarted]);
    expect(s?.kind).toBe("starting");
  });

  it("surfaces a run.phase message (preparing_workdir)", () => {
    const phase: Envelope = {
      type: "run.phase",
      session_id: "S",
      event_id: 2,
      phase: "preparing_workdir",
      message: "Preparing an isolated workdir…",
      run_idx: 1,
    };
    const s = deriveStartupStatus([sessionStarted, phase]);
    expect(s?.kind).toBe("preparing_workdir");
    expect(s?.message).toMatch(/preparing/i);
  });

  it("carries retry + backoff details for rate_limit_backoff", () => {
    const phase: Envelope = {
      type: "run.phase",
      session_id: "S",
      event_id: 5,
      phase: "rate_limit_backoff",
      message: "Rate limited…",
      retry: 2,
      max_retries: 3,
      backoff_s: 20,
    };
    const s = deriveStartupStatus([sessionStarted, runStarted, rawEvent, phase]);
    expect(s?.kind).toBe("rate_limit_backoff");
    expect(s?.retry).toBe(2);
    expect(s?.maxRetries).toBe(3);
    expect(s?.backoffS).toBe(20);
  });

  it("surfaces a model_error phase (endpoint/auth failure)", () => {
    const phase: Envelope = {
      type: "run.phase",
      session_id: "S",
      event_id: 5,
      phase: "model_error",
      message: "Model/endpoint error: 401 Unauthorized",
    };
    const s = deriveStartupStatus([sessionStarted, runStarted, phase]);
    expect(s?.kind).toBe("model_error");
    expect(s?.message).toContain("401");
  });

  it("reports 'waiting_model' after run.started with no raw_event yet", () => {
    const s = deriveStartupStatus([sessionStarted, runStarted]);
    expect(s?.kind).toBe("waiting_model");
  });

  it("returns null once a raw_event has arrived (model is active)", () => {
    expect(deriveStartupStatus([sessionStarted, runStarted, rawEvent])).toBeNull();
  });

  it("returns null after run.finished (between runs)", () => {
    const runFinished: Envelope = {
      type: "run.finished",
      session_id: "S",
      event_id: 6,
      run_idx: 1,
      total_runs: 2,
      condition: "baseline",
      rep: 0,
      finished: true,
      interrupted_reason: null,
      verify: {
        status: null,
        passed_count: 0,
        failed_count: 0,
        failed_names: [],
        command: null,
        duration_s: null,
      },
    };
    expect(
      deriveStartupStatus([sessionStarted, runStarted, rawEvent, runFinished]),
    ).toBeNull();
  });

  it("returns null after session.finished", () => {
    const done: Envelope = {
      type: "session.finished",
      session_id: "S",
      event_id: 9,
      duration_s: 1,
    };
    expect(deriveStartupStatus([sessionStarted, done])).toBeNull();
  });

  it("falls back to a default message when run.phase omits one", () => {
    const phase = {
      type: "run.phase",
      session_id: "S",
      event_id: 2,
      phase: "baseline_verify",
    } as Envelope;
    const s = deriveStartupStatus([sessionStarted, phase]);
    expect(s?.kind).toBe("baseline_verify");
    expect(s?.message).toBeTruthy();
  });
});
