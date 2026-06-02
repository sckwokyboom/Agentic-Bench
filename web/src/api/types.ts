// Mirrors the JSON shapes returned by abench_ui FastAPI endpoints.
// Hand-written from spec §6 + server.py — refresh when contract changes.

export interface ExperimentSummary {
  name: string;
  has_fixture: boolean;
  has_reference: boolean;
  has_runs: boolean;
  last_run_at: string | null;
}

export interface RunBatch {
  id: string;
  total_runs: number;
  valid_runs: number;
  success_rate?: number | null;
}

export interface RunSummary {
  condition: string;
  rep: number;
  finished: boolean;
  interrupted_reason: string | null;
  verify_status: VerifyStatus | null;
  success: boolean | null;
  started_at: string;
  duration_s: number | null;
  n_steps: number | null;
  n_tool_calls: number | null;
  n_test_runs: number | null;
  cost: number | null;
}

export interface ConditionSummary {
  name: string;
  runs: number;
  success_rate: number | null;
  metrics: Record<string, { mean: number | null; median: number | null }>;
}

export interface RunsSummary {
  conditions: ConditionSummary[];
  deltas: Record<string, number>;
  total_runs: number;
  valid_runs: number;
}

export type VerifyStatus = "passed" | "failed" | "skipped" | "error" | "timeout";

export interface VerifySummary {
  status: VerifyStatus | null;
  passed_count: number | null;
  failed_count: number | null;
  failed_names: string[];
  command: string | null;
  duration_s: number | null;
}

export interface MetricsJson {
  finished: boolean;
  interrupted_reason: string | null;
  success: boolean | null;
  verify_status: VerifyStatus | null;
  verify_command: string | null;
  verify_duration_s: number | null;
  verify_passed_count: number | null;
  verify_failed_count: number | null;
  verify_failed_names?: string[];
  verify_reason?: string | null;
  verify_message?: string | null;
  isolation_nonce?: string | null;
  n_tests_executed?: number | null;
  tokens_reasoning?: number | null;
  cache_read?: number | null;
  cache_write?: number | null;
  [key: string]: unknown;
}

export type StepKind =
  | "assistant_text" | "reasoning" | "tool_call" | "tool_result" | "file_edit";

export interface Step {
  kind: StepKind;
  ts: number | null;
  turn: number | null;
  message_id?: string | null;
  text?: string | null;
  tool_name?: string | null;
  tool_args?: Record<string, unknown> | null;
  tool_call_id?: string | null;
  output?: string | null;
  exit_code?: number | null;
  path?: string | null;
  patch?: string | null;
}

export interface TurnInfo {
  message_id: string;
  reason: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  tokens_reasoning: number | null;
  cost: number | null;
  started_at: number | null;
  ended_at: number | null;
}

export interface FileChange { path: string; added: number; removed: number; }
export interface FinalDiffSummary {
  files: FileChange[];
  total_added: number;
  total_removed: number;
}

export interface Trace {
  steps: Step[];
  turns: TurnInfo[];
  verify_status: VerifyStatus | null;
  verify_command: string | null;
  verify_duration_s: number | null;
  verify_passed_count: number | null;
  verify_failed_count: number | null;
  verify_failed_names: string[];
  verify_baseline_unknown: boolean;
  verify_reason?: string | null;
  verify_message?: string | null;
  isolation_nonce: string | null;
  final_diff_summary: FinalDiffSummary | null;
  [key: string]: unknown;
}

export interface MethodComparison {
  method_name: string;
  original_lines: string[];
  regen_lines: string[];
  equivalent: boolean;
}

export interface ValidateModelResp {
  // Backend literals from abench_ui/validate.py:
  //   ok             → key configured, model found in catalog
  //   no_credentials → provider has no API key in auth.json
  //   model_not_found→ provider configured but model id not in catalog
  //   malformed      → model id missing provider/ prefix
  status: "ok" | "no_credentials" | "model_not_found" | "malformed";
  provider: string | null;
  suggestions: string[];
}

export interface DetectedVerify {
  command: string | null;
  system: "maven" | "gradle" | "pytest" | "custom" | null;
  ambiguous: boolean;
  candidates: string[];
}

export interface ReverifyResultRow {
  condition: string;
  rep: number;
  status: VerifyStatus | null;
  reason: string;
  message: string;
  passed_count: number | null;
  failed_count: number | null;
}

export interface ReverifyJob {
  state: "running" | "done" | "error";
  total: number;
  done: number;
  current: { condition: string; rep: number } | null;
  results: ReverifyResultRow[];
  error: string | null;
}

export interface ProviderEntry { id: string; configured: boolean; }

export interface SessionState {
  state: "pending" | "running" | "completed" | "cancelled" | "failed";
  started_at: number | null;
  ended_at: number | null;
  total_runs: number;
  current_condition: string | null;
  current_rep: number | null;
}
