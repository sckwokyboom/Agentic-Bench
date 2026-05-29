// Order + display labels for the summary table. "lowerIsBetter" decides delta
// coloring: a negative delta on these is the desired RAG effect (green).
export const SUMMARY_METRICS: { key: string; label: string; lowerIsBetter: boolean }[] = [
  { key: "n_steps", label: "steps", lowerIsBetter: true },
  { key: "n_reads", label: "reads", lowerIsBetter: true },
  { key: "n_searches", label: "searches", lowerIsBetter: true },
  { key: "n_test_runs", label: "test runs", lowerIsBetter: true },
  { key: "duration_s", label: "duration (s)", lowerIsBetter: true },
  { key: "time_to_first_edit_s", label: "time to first edit (s)", lowerIsBetter: true },
  { key: "n_tool_calls", label: "tool calls", lowerIsBetter: true },
  { key: "cost", label: "cost ($)", lowerIsBetter: true },
];
