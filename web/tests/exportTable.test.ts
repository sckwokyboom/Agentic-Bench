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
        n_steps: { mean: 12, median: 11 },
        duration_s: { mean: 100, median: 100 },
      },
    },
    {
      name: "augmented", runs: 3, success_rate: 2 / 3,
      metrics: {
        n_steps: { mean: 15, median: 14 },
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
    n_tests_executed: 2200, tests_pass_rate: 1.0, tokens_in: 10000, tokens_out: 2000,
    n_reads: 5, n_searches: 3, cost: 0.0234, n_service_errors: 0,
    tool_calls_by_name: { bash: 8, read: 5 },
    obs_tokens_total: 12000, obs_tokens_by_tool: { bash: 8000, read: 4000 },
  },
  {
    condition: "augmented", rep: 0, finished: true, interrupted_reason: null,
    verify_status: "failed", success: false, started_at: "t",
    duration_s: 90, n_steps: 15, n_tool_calls: 9, n_test_runs: 3,
    n_tests_executed: 2200, tests_pass_rate: 0.999, tokens_in: 15000, tokens_out: 3000,
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
    expect(md).toContain("| steps | 12.00 / 11.00 | 15.00 / 14.00 | +25.0% |");
  });
  it("includes the per-run table (concise: tests % + tokens)", () => {
    expect(md).toContain("## Runs (2)");
    expect(md).toContain("| baseline | 0 | passed | pass | 100% | 12 | 8 | 2 | 100.4 | 10000 | 2000 |");
  });
  it("omits batch from the title when absent", () => {
    const m = buildResultsMarkdown({ experimentName: "e" }, summary, []);
    expect(m).toContain("# Results — e\n");
    expect(m).not.toContain("batch");
  });
});

describe("buildRunsCsv", () => {
  it("emits a header with the extended metric columns + one line per run", () => {
    const csv = buildRunsCsv(runs);
    const lines = csv.split("\n");
    const header = lines[0]!;
    for (const col of ["tests_pass_rate", "tests_executed", "tokens_in",
      "tokens_out", "reads", "searches", "tool_calls_by_name",
      "obs_tokens_total", "obs_tokens_by_tool"]) {
      expect(header).toContain(col);
    }
    const cols = lines[1]!.split(",");
    const idx = (name: string) => header.split(",").indexOf(name);
    expect(cols[idx("condition")]).toBe("baseline");
    expect(cols[idx("tests_pass_rate")]).toBe("1.0000");
    expect(cols[idx("tests_executed")]).toBe("2200");
    expect(cols[idx("tokens_in")]).toBe("10000");
    expect(cols[idx("obs_tokens_total")]).toBe("12000");
    // tool_calls_by_name + obs_tokens_by_tool are JSON (quoted, contain commas)
    expect(lines[1]).toContain('{""bash"":8');
    expect(lines[1]).toContain('{""bash"":8000');
  });
  it("breaks the cheating verdict down into signal types + target_similarity", () => {
    const run: RunSummary = {
      ...runs[1]!,
      cheating: {
        verdict: "suspicious",
        signals: [
          { type: "fs_wide_search", evidence: ["grep -r x /"] },
          { type: "output_matches_original", evidence: ["identical"] },
        ],
        target_similarity: 0.9987,
      },
    };
    const csv = buildRunsCsv([run]);
    const header = csv.split("\n")[0]!.split(",");
    const cells = csv.split("\n")[1]!.split(",");
    const at = (name: string) => cells[header.indexOf(name)];
    expect(at("cheating")).toBe("suspicious");
    expect(at("cheating_signals")).toBe("fs_wide_search|output_matches_original");
    expect(at("target_similarity")).toBe("0.9987");
  });

  it("emits just the header for no runs", () => {
    expect(buildRunsCsv([]).split("\n")).toHaveLength(1);
  });
});
