import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import RunsTable from "../src/components/RunsTable";
import type { RunSummary } from "../src/api/types";

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

// The per-condition stuck/looping aggregate moved out of SummaryTable when it
// became the panel-driven comparison view: interrupted + crashed counts are now
// summarised in its validity footer (driven by build_panel), and per-run looping
// is still flagged by RunsTable above. See SummaryTable.test.tsx.
