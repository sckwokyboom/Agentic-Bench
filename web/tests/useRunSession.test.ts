import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useRunSession } from "../src/ws/useRunSession";

// Minimal WebSocket mock that records URLs and lets us push messages.
class FakeWS {
  static instances: FakeWS[] = [];
  url: string;
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  readyState = 0;
  constructor(url: string) {
    this.url = url;
    FakeWS.instances.push(this);
    queueMicrotask(() => {
      this.readyState = 1;
      this.onopen?.(new Event("open"));
    });
  }
  send() {}
  close() {
    this.onclose?.(new CloseEvent("close"));
  }
  push(env: object) {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(env) }));
  }
}

beforeEach(() => {
  FakeWS.instances = [];
  // jsdom defines WebSocket as read-only, so inject via vi.stubGlobal.
  vi.stubGlobal("WebSocket", FakeWS as unknown as typeof WebSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useRunSession", () => {
  it("connects to /ws/sessions/{sid}?last_event_id=0 initially", async () => {
    renderHook(() => useRunSession("S1"));
    await waitFor(() => expect(FakeWS.instances).toHaveLength(1));
    expect(FakeWS.instances[0]!.url).toContain("/ws/sessions/S1");
    expect(FakeWS.instances[0]!.url).toContain("last_event_id=0");
  });

  it("accumulates envelopes and exposes them in order", async () => {
    const { result } = renderHook(() => useRunSession("S2"));
    await waitFor(() => expect(FakeWS.instances).toHaveLength(1));
    act(() => {
      FakeWS.instances[0]!.push({
        type: "session.started",
        session_id: "S2",
        event_id: 1,
        total_runs: 2,
        conditions: ["a"],
      });
      FakeWS.instances[0]!.push({
        type: "run.started",
        session_id: "S2",
        event_id: 2,
        run_idx: 1,
        total_runs: 2,
        condition: "a",
        rep: 0,
      });
    });
    await waitFor(() => expect(result.current.envelopes).toHaveLength(2));
    expect(result.current.lastEventId).toBe(2);
  });

  it("reconnects with last_event_id on close", async () => {
    renderHook(() => useRunSession("S3"));
    await waitFor(() => expect(FakeWS.instances).toHaveLength(1));
    act(() => {
      FakeWS.instances[0]!.push({
        type: "session.started",
        session_id: "S3",
        event_id: 4,
        total_runs: 1,
        conditions: ["x"],
      });
      FakeWS.instances[0]!.close();
    });
    await waitFor(() => expect(FakeWS.instances).toHaveLength(2));
    expect(FakeWS.instances[1]!.url).toContain("last_event_id=4");
  });

  it("skips a replayed duplicate event_id (appends only once)", async () => {
    const { result } = renderHook(() => useRunSession("S5"));
    await waitFor(() => expect(FakeWS.instances).toHaveLength(1));
    act(() => {
      FakeWS.instances[0]!.push({
        type: "run.started",
        session_id: "S5",
        event_id: 1,
        run_idx: 1,
        total_runs: 2,
        condition: "a",
        rep: 0,
      });
      // Server replay re-sends the SAME event_id after a reconnect overlap.
      FakeWS.instances[0]!.push({
        type: "run.started",
        session_id: "S5",
        event_id: 1,
        run_idx: 1,
        total_runs: 2,
        condition: "a",
        rep: 0,
      });
    });
    await waitFor(() => expect(result.current.envelopes).toHaveLength(1));
    expect(result.current.envelopes).toHaveLength(1);
    expect(result.current.lastEventId).toBe(1);
  });

  it("appends every envelope of a normal increasing sequence", async () => {
    const { result } = renderHook(() => useRunSession("S6"));
    await waitFor(() => expect(FakeWS.instances).toHaveLength(1));
    act(() => {
      for (let id = 1; id <= 4; id += 1) {
        FakeWS.instances[0]!.push({
          type: "run.started",
          session_id: "S6",
          event_id: id,
          run_idx: id,
          total_runs: 4,
          condition: "a",
          rep: id - 1,
        });
      }
    });
    await waitFor(() => expect(result.current.envelopes).toHaveLength(4));
    expect(result.current.lastEventId).toBe(4);
  });

  it("stops reconnecting after session.finished", async () => {
    renderHook(() => useRunSession("S4"));
    await waitFor(() => expect(FakeWS.instances).toHaveLength(1));
    act(() => {
      FakeWS.instances[0]!.push({
        type: "session.finished",
        session_id: "S4",
        event_id: 9,
        duration_s: 1,
      });
      FakeWS.instances[0]!.close();
    });
    // Give a tick.
    await new Promise((r) => setTimeout(r, 50));
    expect(FakeWS.instances).toHaveLength(1);
  });

  it("does NOT reconnect when the server closes an unknown session (code 4004)", async () => {
    const { result } = renderHook(() => useRunSession("S7"));
    await waitFor(() => expect(FakeWS.instances).toHaveLength(1));
    act(() => {
      // Server closes an unknown/expired session with 4004 (no terminal event).
      FakeWS.instances[0]!.onclose?.(new CloseEvent("close", { code: 4004 }));
    });
    await new Promise((r) => setTimeout(r, 1000)); // past RECONNECT_DELAY_MS
    expect(FakeWS.instances).toHaveLength(1);       // did NOT loop/reconnect
    expect(result.current.error).toMatch(/no longer available/i);
  });
});
