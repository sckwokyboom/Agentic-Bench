import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { describe, it, expect } from "vitest";
import { mswServer } from "./setup";
import { useBatches, useTrace, useRunsSummary } from "../src/api/queries";
import type { RunBatch } from "../src/api/types";

function wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

const BATCHES: RunBatch[] = [
  { id: "20260602-120000", total_runs: 4, valid_runs: 4, success_rate: 1 },
  { id: "20260601-090000", total_runs: 4, valid_runs: 2, success_rate: 0.5 },
];

describe("useBatches", () => {
  it("fetches /api/runs/<name>/batches and returns them newest-first", async () => {
    mswServer.use(
      http.get("/api/runs/exp/batches", () => HttpResponse.json(BATCHES)),
    );
    const { result } = renderHook(() => useBatches("exp"), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data).toHaveLength(2);
    // newest-first: first item is the later timestamp.
    expect(result.current.data?.[0]?.id).toBe("20260602-120000");
    expect(result.current.data?.[1]?.id).toBe("20260601-090000");
  });

  it("is disabled when name is undefined (no fetch)", async () => {
    const { result } = renderHook(() => useBatches(undefined), { wrapper: wrapper() });
    expect(result.current.fetchStatus).toBe("idle");
    expect(result.current.data).toBeUndefined();
  });
});

describe("useTrace with batch", () => {
  it("appends ?batch=<id> to the trace URL", async () => {
    let seenBatch: string | null = null;
    mswServer.use(
      http.get("/api/runs/exp/baseline/0/trace", ({ request }) => {
        seenBatch = new URL(request.url).searchParams.get("batch");
        return HttpResponse.json({
          steps: [], turns: [], verify_status: null, verify_command: null,
          verify_duration_s: null, verify_passed_count: null, verify_failed_count: null,
          verify_failed_names: [], verify_baseline_unknown: false,
          isolation_nonce: null, final_diff_summary: null,
        });
      }),
    );
    const { result } = renderHook(
      () => useTrace("exp", "baseline", 0, "20260602-120000"),
      { wrapper: wrapper() },
    );
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(seenBatch).toBe("20260602-120000");
  });

  it("omits ?batch= entirely when batch is unset (newest)", async () => {
    let hadBatchParam = true;
    mswServer.use(
      http.get("/api/runs/exp/baseline/0/trace", ({ request }) => {
        hadBatchParam = new URL(request.url).searchParams.has("batch");
        return HttpResponse.json({
          steps: [], turns: [], verify_status: null, verify_command: null,
          verify_duration_s: null, verify_passed_count: null, verify_failed_count: null,
          verify_failed_names: [], verify_baseline_unknown: false,
          isolation_nonce: null, final_diff_summary: null,
        });
      }),
    );
    const { result } = renderHook(
      () => useTrace("exp", "baseline", 0),
      { wrapper: wrapper() },
    );
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(hadBatchParam).toBe(false);
  });
});

describe("useRunsSummary with batch", () => {
  it("requests the chosen batch's summary", async () => {
    let seenBatch: string | null = null;
    mswServer.use(
      http.get("/api/runs/exp/summary", ({ request }) => {
        seenBatch = new URL(request.url).searchParams.get("batch");
        return HttpResponse.json({
          conditions: [], deltas: {}, total_runs: 0, valid_runs: 0,
        });
      }),
    );
    const { result } = renderHook(
      () => useRunsSummary("exp", "20260601-090000"),
      { wrapper: wrapper() },
    );
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(seenBatch).toBe("20260601-090000");
  });
});
