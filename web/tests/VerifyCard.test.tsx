import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { expect, test } from "vitest";
import { mswServer } from "./setup";
import VerifyCard from "../src/components/VerifyCard";
import type { Trace } from "../src/api/types";

const base: Trace = {
  steps: [], turns: [], verify_status: "error", verify_command: "mvn test",
  verify_duration_s: 12.3, verify_passed_count: 0, verify_failed_count: 0,
  verify_failed_names: [], verify_baseline_unknown: false,
  isolation_nonce: null, final_diff_summary: null,
  verify_reason: "build_failed", verify_message: "build failed — COMPILATION ERROR",
};

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>;
}

test("shows reason, message, build system; opens the log dialog", async () => {
  mswServer.use(http.get("/api/runs/exp/baseline/0/verify_log", () =>
    new HttpResponse("# command: mvn test\n───\nBUILD FAILURE\n", {
      headers: { "content-type": "text/plain" },
    })));
  render(wrap(<VerifyCard trace={base} name="exp" condition="baseline" rep={0} />));
  expect(screen.getByText(/build failed — COMPILATION ERROR/)).toBeInTheDocument();
  expect(screen.getByText("build_failed")).toBeInTheDocument();
  expect(screen.getByText(/Maven/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /view verify output/i }));
  expect(await screen.findByText(/BUILD FAILURE/)).toBeInTheDocument();
});

test("renders nothing when verify_status is null", () => {
  const { container } = render(
    wrap(<VerifyCard trace={{ ...base, verify_status: null }} name="exp" condition="baseline" rep={0} />),
  );
  expect(container.firstChild).toBeNull();
});

test("Re-verify starts a job and polls to done", async () => {
  mswServer.use(
    http.post("/api/verify", () => HttpResponse.json({ verify_id: "v1" })),
    http.get("/api/verify/v1", () => HttpResponse.json({
      state: "done", total: 1, done: 1, current: null, error: null,
      results: [{ condition: "baseline", rep: 0, status: "passed", reason: "passed",
                  message: "ok", passed_count: 5, failed_count: 0 }],
    })),
  );
  render(wrap(<VerifyCard trace={base} name="exp" condition="baseline" rep={0} />));
  await userEvent.click(screen.getByRole("button", { name: /^re-verify$/i }));
  // resolves back to the idle "Re-verify" label once the job reports done
  await screen.findByRole("button", { name: /^re-verify$/i });
});
