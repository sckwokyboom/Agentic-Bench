import { Stack, Typography, Tooltip } from "@mui/material";
import { formatTokens } from "../lib/formatTokens";
import type { MetricsJson } from "../api/types";

interface Props { metrics: MetricsJson; }

const HELP = {
  steps: "Distinct model steps (turns) in the ReAct chain — one LLM round-trip each (reasoning + tool calls or final text). Fewer for the same outcome = more efficient.",
  "tool calls": "Total tool invocations across the run.",
  "test runs": "How many times the agent invoked a test command.",
  "tests run": "Individual tests those commands actually exercised (parsed from output).",
  reads: "read/open file operations.",
  searches: "grep/glob/list operations — code exploration volume.",
  tokens: "Prompt tokens read (in) / generated (out) over the whole run.",
  cache: "Tokens served from the provider's prompt cache. With run isolation (nonce prefix) on, expect ≈0.",
  cost: "$ at the provider's rates (from opencode).",
} as const;

function Stat({ label, value, help }: { label: string; value: string; help: string }) {
  return (
    <Tooltip title={help}>
      <Typography variant="body2" color="text.secondary" sx={{ cursor: "help" }}>
        {label}: <b>{value}</b>
      </Typography>
    </Tooltip>
  );
}

export default function AggregateStatsBar({ metrics: m }: Props) {
  const num = (v: unknown) => (typeof v === "number" ? v : null);
  return (
    <Stack direction="row" spacing={2} flexWrap="wrap" alignItems="center">
      <Stat label="steps" value={String(num(m.n_steps) ?? "—")} help={HELP.steps} />
      <Stat label="tool calls" value={String(num(m.n_tool_calls) ?? "—")} help={HELP["tool calls"]} />
      <Stat label="reads" value={String(num(m.n_reads) ?? "—")} help={HELP.reads} />
      <Stat label="searches" value={String(num(m.n_searches) ?? "—")} help={HELP.searches} />
      <Stat label="test runs" value={String(num(m.n_test_runs) ?? "—")} help={HELP["test runs"]} />
      <Stat label="tests run" value={String(num(m.n_tests_executed) ?? "—")} help={HELP["tests run"]} />
      <Stat label="tokens" value={`${formatTokens(num(m.tokens_in))} in / ${formatTokens(num(m.tokens_out))} out`} help={HELP.tokens} />
      <Stat label="cache" value={`${formatTokens(num(m.cache_read))} r / ${formatTokens(num(m.cache_write))} w`} help={HELP.cache} />
      <Stat label="cost" value={num(m.cost) != null ? `$${num(m.cost)!.toFixed(4)}` : "—"} help={HELP.cost} />
    </Stack>
  );
}
