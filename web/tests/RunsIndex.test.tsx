import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { expect, test } from "vitest";
import { mswServer } from "./setup";
import RunsIndex from "../src/pages/RunsIndex";

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  );
}

test("lists only experiments that have runs", async () => {
  mswServer.use(http.get("/api/experiments", () => HttpResponse.json([
    { name: "with-runs", has_fixture: true, has_reference: true, has_runs: true, last_run_at: "2026-05-29T10:00:00" },
    { name: "no-runs", has_fixture: true, has_reference: false, has_runs: false, last_run_at: null },
  ])));
  render(wrap(<RunsIndex />));
  await waitFor(() => expect(screen.getByText("with-runs")).toBeInTheDocument());
  expect(screen.queryByText("no-runs")).not.toBeInTheDocument();
});
