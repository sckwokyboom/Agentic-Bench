import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { describe, it, expect } from "vitest";
import { mswServer } from "./setup";
import RunLogToggle from "../src/components/RunLogToggle";

function renderWith(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("RunLogToggle", () => {
  it("lazy-fetches the run log only after expanding", async () => {
    let hits = 0;
    mswServer.use(
      http.get("/api/runs/exp/baseline/0/run_log", () => {
        hits += 1;
        return new HttpResponse("hello from run.log", {
          headers: { "content-type": "text/plain" },
        });
      }),
    );
    renderWith(<RunLogToggle name="exp" condition="baseline" rep={0} />);
    // Collapsed → no fetch yet.
    expect(hits).toBe(0);
    await userEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(screen.getByText(/hello from run\.log/)).toBeInTheDocument());
    expect(hits).toBe(1);
  });

  it("switches between the readable and full (debug) logs", async () => {
    mswServer.use(
      http.get("/api/runs/exp/baseline/0/run_log", () =>
        new HttpResponse("READABLE LINES", { headers: { "content-type": "text/plain" } })),
      http.get("/api/runs/exp/baseline/0/debug_log", () =>
        new HttpResponse("FULL FIREHOSE", { headers: { "content-type": "text/plain" } })),
    );
    renderWith(<RunLogToggle name="exp" condition="baseline" rep={0} />);
    await userEvent.click(screen.getByRole("button", { name: /show run log/i }));
    await waitFor(() => expect(screen.getByText("READABLE LINES")).toBeInTheDocument());
    // Switch to the full (debug) view → fetches the debug_log endpoint.
    await userEvent.click(screen.getByRole("button", { name: /full \(debug\)/i }));
    await waitFor(() => expect(screen.getByText("FULL FIREHOSE")).toBeInTheDocument());
  });

  it("shows a graceful 'no log' message on 404", async () => {
    mswServer.use(
      http.get("/api/runs/exp/baseline/1/run_log", () =>
        new HttpResponse("not found", { status: 404 })),
    );
    renderWith(<RunLogToggle name="exp" condition="baseline" rep={1} />);
    await userEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(screen.getByText(/no run log/i)).toBeInTheDocument());
  });
});
