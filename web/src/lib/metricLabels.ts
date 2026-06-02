// Order + display labels for the summary table.
// "direction" decides delta coloring: lower=better → negative Δ green; higher=better
// → positive Δ green; neutral → never colored (informational).
export type Direction = "lower" | "higher" | "neutral";
export const SUMMARY_METRICS: { key: string; label: string; direction: Direction; help?: string }[] = [
  { key: "n_steps", label: "steps", direction: "lower" },
  { key: "n_reads", label: "reads", direction: "lower" },
  { key: "n_searches", label: "searches", direction: "lower" },
  { key: "n_test_runs", label: "test runs", direction: "lower" },
  { key: "n_tests_executed", label: "tests executed", direction: "neutral",
    help: "Individual tests the agent ran — more isn't inherently better." },
  { key: "duration_s", label: "duration (s)", direction: "lower" },
  { key: "time_to_first_edit_s", label: "time to first edit (s)", direction: "lower" },
  { key: "n_tool_calls", label: "tool calls", direction: "lower" },
  { key: "tokens_in", label: "tokens read (in)", direction: "lower" },
  { key: "tokens_out", label: "tokens generated (out)", direction: "lower" },
  { key: "tokens_reasoning", label: "reasoning tokens", direction: "lower" },
  { key: "cache_read", label: "cache read", direction: "neutral",
    help: "From the provider's prompt cache; ≈0 expected with run isolation on." },
  { key: "cache_write", label: "cache write", direction: "neutral",
    help: "Tokens written to the provider's prompt cache — informational, not better/worse." },
  { key: "cost", label: "cost ($)", direction: "lower" },
];
