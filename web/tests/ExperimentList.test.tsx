import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { mswServer } from "./setup";
import ExperimentList from "../src/pages/ExperimentList";

// Spy component that records the current pathname into a ref the test can read.
let lastPath = "";
function LocationSpy() {
  lastPath = useLocation().pathname;
  return null;
}

function renderPage() {
  lastPath = "";
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/experiments"]}>
        <ExperimentList />
        <LocationSpy />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("ExperimentList shows experiments from API", async () => {
  mswServer.use(http.get("/api/experiments", () =>
    HttpResponse.json([
      { name: "wc",     has_fixture: true,  has_reference: true, has_runs: true,  last_run_at: "2026-05-28T10:00:00" },
      { name: "broken", has_fixture: false, has_reference: true, has_runs: false, last_run_at: null },
    ])));
  renderPage();
  expect(await screen.findByText("wc")).toBeInTheDocument();
  expect(await screen.findByText("broken")).toBeInTheDocument();
});

test("Run button calls POST /api/runs and navigates", async () => {
  mswServer.use(
    http.get("/api/experiments", () =>
      HttpResponse.json([
        { name: "wc", has_fixture: true, has_reference: true, has_runs: false, last_run_at: null },
      ])),
    http.post("/api/runs", async ({ request }) => {
      const body = await request.json() as { experiment_name: string };
      expect(body.experiment_name).toBe("wc");
      return HttpResponse.json({ session_id: "S1" });
    }),
  );
  renderPage();
  const runBtn = await screen.findByRole("button", { name: /run/i });
  await userEvent.click(runBtn);
  await waitFor(() => expect(lastPath).toBe("/runs/sessions/S1"));
});

test("status pill reflects missing fixture", async () => {
  mswServer.use(http.get("/api/experiments", () =>
    HttpResponse.json([
      { name: "broken", has_fixture: false, has_reference: true, has_runs: false, last_run_at: null },
    ])));
  renderPage();
  expect(await screen.findByText(/no fixture/i)).toBeInTheDocument();
});
