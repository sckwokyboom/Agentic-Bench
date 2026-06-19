import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import RunsTable from "../src/components/RunsTable";
import SummaryTable from "../src/components/SummaryTable";
import type { RunSummary, RunsSummary } from "../src/api/types";

function run(over: Partial<RunSummary>): RunSummary {
  return {
    condition: "augmented",
    rep: 0,
    finished: true,
    interrupted_reason: null,
    verify_status: null,
    success: false,
    started_at: "2026-06-18T00:00:00Z",
    duration_s: 1,
    n_steps: 1,
    n_tool_calls: 1,
    n_test_runs: 0,
    cost: 0,
    made_source_changes: true, // avoid the "no edits" badge interfering
    ...over,
  };
}

describe("RunsTable stuck badge", () => {
  it("shows a 'stuck (looping)' badge for a looped run", () => {
    render(<RunsTable rows={[run({ stuck: true, interrupted_reason: "looping" })]} onOpen={() => {}} />);
    expect(screen.getByTitle("stuck (looping)")).toBeInTheDocument();
  });

  it("falls back to interrupted_reason when the stuck flag is absent (old metrics)", () => {
    render(<RunsTable rows={[run({ interrupted_reason: "looping" })]} onOpen={() => {}} />);
    expect(screen.getByTitle("stuck (looping)")).toBeInTheDocument();
  });

  it("shows NO stuck badge for a normal run", () => {
    render(<RunsTable rows={[run({})]} onOpen={() => {}} />);
    expect(screen.queryByTitle("stuck (looping)")).toBeNull();
  });
});

describe("SummaryTable stuck row", () => {
  function summary(conditions: RunsSummary["conditions"]): RunsSummary {
    return { conditions, deltas: {}, total_runs: 0, valid_runs: 0 };
  }

  it("shows a 'stuck (looping)' row with per-condition counts when any condition looped", () => {
    render(<SummaryTable summary={summary([
      { name: "baseline", runs: 2, stuck: 0, success_rate: 1, tests_pass_rate: null, metrics: {} },
      { name: "augmented", runs: 1, stuck: 2, success_rate: 0, tests_pass_rate: null, metrics: {} },
    ])} />);
    expect(screen.getByText(/stuck \(looping\)/i)).toBeInTheDocument();
  });

  it("hides the stuck row entirely when no condition looped", () => {
    render(<SummaryTable summary={summary([
      { name: "baseline", runs: 2, stuck: 0, success_rate: 1, tests_pass_rate: null, metrics: {} },
    ])} />);
    expect(screen.queryByText(/stuck \(looping\)/i)).toBeNull();
  });
});
