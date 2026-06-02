import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { describe, it, expect } from "vitest";
import { mswServer } from "./setup";
import ExperimentResults from "../src/pages/ExperimentResults";

const NEWEST = "20260602-120000";
const OLDER = "20260601-090000";

function emptySummary() {
  return { conditions: [], deltas: {}, total_runs: 0, valid_runs: 0 };
}

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/runs/exp"]}>
        <Routes>
          <Route path="/runs/:name" element={<ExperimentResults />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function installHandlers(onSummary: (batch: string | null) => void) {
  mswServer.use(
    http.get("/api/runs/exp/batches", () => HttpResponse.json([
      { id: NEWEST, total_runs: 4, valid_runs: 4, success_rate: 1 },
      { id: OLDER, total_runs: 4, valid_runs: 2, success_rate: 0.5 },
    ])),
    http.get("/api/runs/exp/summary", ({ request }) => {
      onSummary(new URL(request.url).searchParams.get("batch"));
      return HttpResponse.json(emptySummary());
    }),
    http.get("/api/runs/exp", () => HttpResponse.json([])),
  );
}

describe("ExperimentResults batch selector", () => {
  it("renders both batch options and defaults to the newest, requesting its summary", async () => {
    const summaryBatches: (string | null)[] = [];
    installHandlers((b) => summaryBatches.push(b));

    render(wrap());

    // The Select shows the newest batch's formatted label by default.
    const combo = await screen.findByRole("combobox", { name: /batch/i });
    await waitFor(() =>
      expect(within(combo).getByText(/2026-06-02 12:00:00 UTC/)).toBeInTheDocument());

    // Default summary request carried the newest batch id.
    await waitFor(() => expect(summaryBatches).toContain(NEWEST));
    expect(summaryBatches).not.toContain(OLDER);

    // Opening the dropdown reveals both options.
    await userEvent.click(combo);
    const listbox = await screen.findByRole("listbox");
    expect(within(listbox).getByText(/2026-06-02 12:00:00 UTC/)).toBeInTheDocument();
    expect(within(listbox).getByText(/2026-06-01 09:00:00 UTC/)).toBeInTheDocument();
  });

  it("switching the batch refetches the summary for the chosen batch", async () => {
    const summaryBatches: (string | null)[] = [];
    installHandlers((b) => summaryBatches.push(b));

    render(wrap());

    const combo = await screen.findByRole("combobox", { name: /batch/i });
    await waitFor(() => expect(summaryBatches).toContain(NEWEST));

    await userEvent.click(combo);
    const listbox = await screen.findByRole("listbox");
    await userEvent.click(within(listbox).getByText(/2026-06-01 09:00:00 UTC/));

    await waitFor(() => expect(summaryBatches).toContain(OLDER));
  });
});
