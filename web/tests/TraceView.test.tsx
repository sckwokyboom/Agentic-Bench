import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { describe, it, expect } from "vitest";
import { mswServer } from "./setup";
import TraceView from "../src/pages/TraceView";

function wrap(initialPath: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/runs/:name/:condition/:rep" element={<TraceView />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("TraceView back navigation", () => {
  it("offers a 'Back to results' link (preserving the batch) even when the trace fails to load", async () => {
    mswServer.use(
      // The trace itself 500s — the failed-trace screen must still let you back out.
      http.get("/api/runs/exp/baseline/0/trace", () => new HttpResponse(null, { status: 500 })),
      http.get("/api/runs/exp/baseline/0/events", () => HttpResponse.text("")),
      http.get("/api/runs/exp/baseline/0/metrics", () => HttpResponse.json({})),
      http.get("/api/runs/exp", () => HttpResponse.json([])),
    );
    render(wrap("/runs/exp/baseline/0?batch=20260630-120000"));

    await waitFor(() =>
      expect(screen.getByText(/failed to load trace/i)).toBeInTheDocument());
    const back = screen.getByRole("link", { name: /back to results/i });
    // Returns to the comparison page for this experiment, keeping the batch.
    expect(back).toHaveAttribute("href", "/runs/exp?batch=20260630-120000");
  });
});
