import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { expect, test } from "vitest";
import { mswServer } from "./setup";
import ActiveRunsBanner from "../src/components/ActiveRunsBanner";

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/experiments"]}>
        <Routes>
          <Route path="/experiments" element={ui} />
          <Route path="/runs/sessions/:sid" element={<div>LIVE PAGE</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const RUNNING = {
  session_id: "S1",
  experiment_name: "exp-a",
  batch_id: "20260604-120000",
  state: "running",
  started_at: 1,
  ended_at: null,
  total_runs: 2,
  current_idx: 1,
  current_condition: "baseline",
  current_rep: 0,
  conditions: ["baseline"],
};

test("renders nothing when there are no active sessions", async () => {
  mswServer.use(http.get("/api/sessions", () => HttpResponse.json([])));
  const { container } = render(wrap(<ActiveRunsBanner />));
  // Give the query a tick; banner must stay empty.
  await new Promise((r) => setTimeout(r, 50));
  expect(container).toBeEmptyDOMElement();
});

test("lists a running session with progress and an Open live button", async () => {
  mswServer.use(http.get("/api/sessions", () => HttpResponse.json([RUNNING])));
  render(wrap(<ActiveRunsBanner />));
  await waitFor(() => expect(screen.getByText("exp-a")).toBeInTheDocument());
  expect(screen.getByText("run 1/2")).toBeInTheDocument();
  expect(screen.getByText(/baseline · rep 0/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /open live/i })).toBeInTheDocument();
});

test("Open live navigates to the live run page", async () => {
  mswServer.use(http.get("/api/sessions", () => HttpResponse.json([RUNNING])));
  render(wrap(<ActiveRunsBanner />));
  const btn = await screen.findByRole("button", { name: /open live/i });
  await userEvent.click(btn);
  expect(screen.getByText("LIVE PAGE")).toBeInTheDocument();
});
