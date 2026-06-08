import type { RunsSummary, RunSummary } from "../api/types";
import { SUMMARY_METRICS } from "./metricLabels";

// ── Generic renderers ────────────────────────────────────────────────────────

/** A GitHub-flavoured Markdown table (renders in most chats + parses cleanly
 * for an LLM). */
export function toMarkdownTable(headers: string[], rows: string[][]): string {
  const head = `| ${headers.join(" | ")} |`;
  const sep = `| ${headers.map(() => "---").join(" | ")} |`;
  if (rows.length === 0) return `${head}\n${sep}`;
  const body = rows.map((r) => `| ${r.join(" | ")} |`).join("\n");
  return `${head}\n${sep}\n${body}`;
}

function csvCell(v: string): string {
  return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
}

export function toCsv(headers: string[], rows: string[][]): string {
  return [headers, ...rows].map((r) => r.map(csvCell).join(",")).join("\n");
}

// ── Aggregate (summary) table ─────────────────────────────────────────────────

const fmtMean = (v: number | null | undefined): string =>
  v == null ? "—" : v.toFixed(2);

function summaryTable(summary: RunsSummary): { headers: string[]; rows: string[][] } {
  const conditions = summary.conditions;
  const hasDelta = Object.keys(summary.deltas).length > 0;
  const headers = ["metric", ...conditions.map((c) => `${c.name} (n=${c.runs})`)];
  if (hasDelta) headers.push("Δ aug vs base");

  const rows: string[][] = [];

  // success rate (top-level per-condition field; delta is percentage-POINTS)
  const base = conditions.find((c) => c.name === "baseline");
  const aug = conditions.find((c) => c.name === "augmented");
  const srDeltaPP =
    base?.success_rate != null && aug?.success_rate != null
      ? (aug.success_rate - base.success_rate) * 100
      : null;
  const srRow = [
    "success rate",
    ...conditions.map((c) =>
      c.success_rate == null ? "—" : `${(c.success_rate * 100).toFixed(0)}%`),
  ];
  if (hasDelta) {
    srRow.push(srDeltaPP == null ? "—" : `${srDeltaPP > 0 ? "+" : ""}${srDeltaPP.toFixed(0)}pp`);
  }
  rows.push(srRow);

  for (const m of SUMMARY_METRICS) {
    const row = [m.label, ...conditions.map((c) => fmtMean(c.metrics[m.key]?.mean))];
    if (hasDelta) {
      const d = summary.deltas[m.key];
      row.push(d == null ? "—" : `${d > 0 ? "+" : ""}${d.toFixed(1)}%`);
    }
    rows.push(row);
  }
  return { headers, rows };
}

// ── Per-run table ─────────────────────────────────────────────────────────────

const RUN_HEADERS = [
  "condition", "rep", "verify", "success", "tests_pass_rate",
  "verify_passed", "verify_failed", "duration_s", "steps", "tool_calls",
  "reads", "searches", "test_runs", "tests_executed", "files_edited",
  "tokens_in", "tokens_out", "tokens_reasoning", "cost", "service_errors",
  "cheating", "tool_calls_by_name",
];

function runCells(r: RunSummary): string[] {
  const n = (v: number | null | undefined, d = 0) => (v == null ? "" : v.toFixed(d));
  return [
    r.condition,
    String(r.rep),
    r.verify_status ?? "",
    r.success == null ? "" : r.success ? "pass" : "fail",
    r.tests_pass_rate == null ? "" : r.tests_pass_rate.toFixed(4),
    n(r.verify_passed_count),
    n(r.verify_failed_count),
    n(r.duration_s, 1),
    n(r.n_steps),
    n(r.n_tool_calls),
    n(r.n_reads),
    n(r.n_searches),
    n(r.n_test_runs),
    n(r.n_tests_executed),
    n(r.n_files_edited),
    n(r.tokens_in),
    n(r.tokens_out),
    n(r.tokens_reasoning),
    n(r.cost, 4),
    String(r.n_service_errors ?? 0),
    r.cheating?.verdict ?? "",
    r.tool_calls_by_name ? JSON.stringify(r.tool_calls_by_name) : "",
  ];
}

// ── Public builders ────────────────────────────────────────────────────────────

export interface ExportMeta {
  experimentName: string;
  batchLabel?: string | null;
}

/** A self-contained Markdown report (title + aggregate + per-run tables) — the
 * thing you paste into an LLM or a team chat. */
export function buildResultsMarkdown(
  meta: ExportMeta,
  summary: RunsSummary | null | undefined,
  runs: RunSummary[] | null | undefined,
): string {
  const title =
    `# Results — ${meta.experimentName}` +
    (meta.batchLabel ? ` · batch ${meta.batchLabel}` : "");
  const parts = [title];
  if (summary && summary.conditions.length > 0) {
    const { headers, rows } = summaryTable(summary);
    parts.push(
      `\n## Aggregate (mean per condition; valid runs only)\n\n${toMarkdownTable(headers, rows)}`,
    );
  }
  if (runs && runs.length > 0) {
    // Concise per-run table for chat/LLM (the CSV export carries every column).
    parts.push(
      `\n## Runs (${runs.length})\n\n${toMarkdownTable(MD_RUN_HEADERS, runs.map(mdRunCells))}`,
    );
  }
  return `${parts.join("\n")}\n`;
}

const MD_RUN_HEADERS = [
  "condition", "rep", "verify", "success", "tests %",
  "steps", "tool_calls", "test_runs", "duration_s", "tokens_in", "tokens_out",
];

function mdRunCells(r: RunSummary): string[] {
  const n = (v: number | null | undefined, d = 0) => (v == null ? "—" : v.toFixed(d));
  const pct = r.tests_pass_rate == null ? "—" : `${(r.tests_pass_rate * 100).toFixed(1)}%`;
  return [
    r.condition,
    String(r.rep),
    r.verify_status ?? "—",
    r.success == null ? "—" : r.success ? "pass" : "fail",
    pct,
    n(r.n_steps),
    n(r.n_tool_calls),
    n(r.n_test_runs),
    n(r.duration_s, 1),
    n(r.tokens_in),
    n(r.tokens_out),
  ];
}

/** The per-run table as CSV (for spreadsheets / quick LLM ingestion). */
export function buildRunsCsv(runs: RunSummary[] | null | undefined): string {
  return toCsv(RUN_HEADERS, runs ? runs.map(runCells) : []);
}
