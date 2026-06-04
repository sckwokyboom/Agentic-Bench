import { describe, it, expect } from "vitest";
import {
  toMarkdownTable, toCsv, buildResultsMarkdown, buildRunsCsv,
} from "../src/lib/exportTable";
import type { RunsSummary, RunSummary } from "../src/api/types";

const summary: RunsSummary = {
  total_runs: 6,
  valid_runs: 6,
  deltas: { n_steps: 25.0, duration_s: -10.0 },
  conditions: [
    {
      name: "baseline", runs: 3, success_rate: 1.0,
      metrics: {
        n_steps: { mean: 12, median: 12 },
        duration_s: { mean: 100, median: 100 },
      },
    },
    {
      name: "augmented", runs: 3, success_rate: 2 / 3,
      metrics: {
        n_steps: { mean: 15, median: 15 },
        duration_s: { mean: 90, median: 90 },
      },
    },
  ],
};

const runs: RunSummary[] = [
  {
    condition: "baseline", rep: 0, finished: true, interrupted_reason: null,
    verify_status: "passed", success: true, started_at: "t",
    duration_s: 100.4, n_steps: 12, n_tool_calls: 8, n_test_runs: 2,
    cost: 0.0234, n_service_errors: 0,
  },
  {
    condition: "augmented", rep: 0, finished: true, interrupted_reason: null,
    verify_status: "failed", success: false, started_at: "t",
    duration_s: 90, n_steps: 15, n_tool_calls: 9, n_test_runs: 3,
    cost: 0.0312, n_service_errors: 1,
  },
];

describe("toMarkdownTable", () => {
  it("renders header, separator, and rows", () => {
    expect(toMarkdownTable(["m", "v"], [["steps", "12"]])).toBe(
      "| m | v |\n| --- | --- |\n| steps | 12 |",
    );
  });
  it("renders header + separator only when there are no rows", () => {
    expect(toMarkdownTable(["a", "b"], [])).toBe("| a | b |\n| --- | --- |");
  });
});

describe("toCsv", () => {
  it("quotes cells containing comma, quote, or newline", () => {
    expect(toCsv(["a", "b"], [["x,y", 'he said "hi"']])).toBe(
      'a,b\n"x,y","he said ""hi"""',
    );
  });
});

describe("buildResultsMarkdown", () => {
  const md = buildResultsMarkdown(
    { experimentName: "exp-x", batchLabel: "latest" }, summary, runs,
  );
  it("has a title with experiment + batch", () => {
    expect(md).toContain("# Results — exp-x · batch latest");
  });
  it("includes the aggregate table with success rate + a delta", () => {
    expect(md).toContain("## Aggregate");
    expect(md).toContain("| success rate | 100% | 67% | -33pp |");
    expect(md).toContain("| steps | 12.00 | 15.00 | +25.0% |");
  });
  it("includes the per-run table", () => {
    expect(md).toContain("## Runs (2)");
    expect(md).toContain("| baseline | 0 | passed | pass | 100.4 | 12 | 8 | 2 | 0.0234 | 0 |");
  });
  it("omits batch from the title when absent", () => {
    const m = buildResultsMarkdown({ experimentName: "e" }, summary, []);
    expect(m).toContain("# Results — e\n");
    expect(m).not.toContain("batch");
  });
});

describe("buildRunsCsv", () => {
  it("emits the header row and one line per run", () => {
    const csv = buildRunsCsv(runs);
    const lines = csv.split("\n");
    expect(lines[0]).toBe(
      "condition,rep,verify,success,duration_s,steps,tool_calls,test_runs,cost,service_errors",
    );
    expect(lines[1]).toBe("baseline,0,passed,pass,100.4,12,8,2,0.0234,0");
    expect(lines[2]).toBe("augmented,0,failed,fail,90.0,15,9,3,0.0312,1");
  });
  it("emits just the header for no runs", () => {
    expect(buildRunsCsv([]).split("\n")).toHaveLength(1);
  });
});
