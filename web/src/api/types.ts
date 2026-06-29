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

export interface CheatingSignal {
  type: string;
  evidence: string[];
}
export interface CheatingReport {
  verdict: "clean" | "suspicious";
  signals: CheatingSignal[];
  target_similarity: number | null;
}

export interface RunSummary {
  condition: string;
  rep: number;
  finished: boolean;
  interrupted_reason: string | null;
  stuck?: boolean;              // killed by the loop watchdog (agent repeated a step)
  stop_reason?: string | null;  // model's final finish reason (stop/length/error/…)
  verify_status: VerifyStatus | null;
  success: boolean | null;
  started_at: string;
  duration_s: number | null;
  n_steps: number | null;
  n_tool_calls: number | null;
  n_test_runs: number | null;
  n_tests_executed?: number | null;
  tests_pass_rate?: number | null;   // passed / (passed+failed), 0..1
  verify_passed_count?: number | null;
  verify_failed_count?: number | null;
  cost: number | null;
  tokens_in?: number | null;
  tokens_out?: number | null;
  tokens_reasoning?: number | null;
  n_reads?: number | null;
  n_searches?: number | null;
  n_files_edited?: number | null;
  tool_calls_by_name?: Record<string, number> | null;
  obs_tokens_total?: number | null;                       // est. tokens of tool outputs (context cost)
  obs_tokens_by_tool?: Record<string, number> | null;     // est. observation tokens per tool
  // Validity signals (Tasks A/B): surfaced so the table/results can flag runs
  // that scored without doing meaningful work (proxy errors, no edits, an
  // insensitive verify).
  n_service_errors?: number;
  n_rate_limits?: number;
  made_source_changes?: boolean;
  verify_insensitive?: boolean;
  // Advisory cheating detector (network / VCS history / outside-FS / broad
  // search / output≈original).
  cheating?: CheatingReport | null;
}

export interface ConditionSummary {
  name: string;
  runs: number;
  stuck?: number;                   // # runs killed by the loop watchdog (looping)
  success_rate: number | null;
  tests_pass_rate?: number | null;  // mean passed/(passed+failed) over valid runs
  metrics: Record<string, { mean: number | null; median: number | null }>;
}

export interface RunsSummary {
  conditions: ConditionSummary[];
  deltas: Record<string, number>;
  total_runs: number;
  valid_runs: number;
}

// ── Screening comparison panel (GET /api/runs/{name}/panel) ──────────────────
// Mirrors abench.screening.build_panel. Each metric carries the chosen aggregate
// (median|mean) plus, for non-baseline conditions, the ratio vs baseline with a
// bootstrap 95% CI and Cliff's delta.
export type Aggregate = "median" | "mean";
export type Verdict = "baseline" | "promising" | "inconclusive" | "dominated";

export interface PanelMetric {
  value: number | null;                       // the aggregate (median|mean) for this condition
  ratio: number | null;                        // value / baseline value (null on baseline)
  ci: [number | null, number | null] | null;   // bootstrap 95% CI of the ratio
  cliffs: number | null;                       // Cliff's delta in [-1, 1]
}

export interface PanelPass {
  k: number;                                   // passing runs
  n: number;                                   // scored runs (valid, verdict usable)
  rate: number | null;                         // k / n
  wilson: [number, number] | null;             // Wilson score interval on the rate
  beta_p_gt_baseline: number | null;           // Bayesian P(this rate > baseline rate)
}

export interface PanelBehavior {
  tool_calls: number | null;                   // Σ tool calls over valid runs
  read_share: number | null;                   // read / search / edit / bash as a share of tool calls
  search_share: number | null;
  edit_share: number | null;
  bash_share: number | null;
  files_edited: number | null;                 // typical (aggregate) files edited
}

export interface PanelCondition {
  name: string;
  n_valid: number;
  n_total: number;
  pass: PanelPass;
  tests_pass_rate: number | null;              // Σpassed / Σ(passed+failed) over valid runs
  cost_per_pass: { tokens: number | null; seconds: number | null };
  behavior: PanelBehavior;
  flags: { interrupted: number; crashed: number; invalid_verify?: number };
  metrics: Record<string, PanelMetric>;
  verdict: Verdict;
}

export interface Panel {
  baseline: string;
  agg: Aggregate;
  total_runs: number;
  valid_runs: number;
  interrupted_runs?: number;
  metric_order: string[];
  conditions: PanelCondition[];
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
  // Validity signals (Tasks A/B).
  n_service_errors?: number;
  n_rate_limits?: number;
  made_source_changes?: boolean;
  verify_insensitive?: boolean;
  cheating?: CheatingReport | null;
  [key: string]: unknown;
}

export type StepKind =
  | "assistant_text" | "reasoning" | "tool_call" | "tool_result" | "file_edit"
  | "controller"      // deterministic phased-orchestrator action (ran suite, accept/revert…)
  | "phase_prompt";   // the exact prompt the controller sent to the model for a phase (LLM input)

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
  phase?: string | null;  // orchestration phase this step belongs to (null = autonomous)
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
  // Model context window (max tokens) — auto-detected or overridden; basis for
  // the "% of context used" display. Null/absent when unknown.
  model_context_window?: number | null;
  final_diff_summary: FinalDiffSummary | null;
  // Validity signals (Tasks A/B). `made_source_changes` is a metrics-only field;
  // for the trace, derive "no edits" from final_diff_summary.files.length.
  n_service_errors?: number;
  verify_insensitive?: boolean;
  service_error_messages?: string[];
  // Phased-orchestration summary (absent on autonomous/baseline traces).
  orchestration_outcome?: string | null;   // green | budget | stuck | compile-fail
  controller_test_runs?: number;
  accepted_rounds?: number;
  reverted_rounds?: number;
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
  //   unverified     → couldn't reach the opencode CLI/registry to check
  status: "ok" | "no_credentials" | "model_not_found" | "malformed" | "unverified";
  provider: string | null;
  suggestions: string[];
}

export interface ValidateReachabilityResp {
  // From abench.reachability: a REAL probe of the configured endpoint+key+model
  // run INSIDE the experiment's sandbox (never the key — only the verdict).
  reachable: boolean;
  reason: string;   // ok | auth | model_not_found | network | tls | http_<code> | probe_failed
  detail: string;   // short, key-scrubbed
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

export interface CostSummary {
  total_cost: number;            // sum of every run's metrics cost, in $
  n_runs: number;                // total runs found across all experiments
  n_runs_with_cost: number;      // runs that reported a cost (rest are free/unpriced)
  by_experiment: Record<string, number>;
}

export interface ProviderEntry { id: string; configured: boolean; }

export interface ModelCatalogEntry { provider: string; id: string }

export interface SessionSummary {
  session_id: string;
  experiment_name: string;
  batch_id: string;
  state: "pending" | "running" | "completed" | "cancelled" | "failed";
  started_at: number | null;
  ended_at: number | null;
  total_runs: number;
  current_idx: number;
  current_condition: string | null;
  current_rep: number | null;
  conditions: string[];
}

// GET /api/sessions/{sid} returns the same enriched shape as each item of
// GET /api/sessions, so a session can be re-opened by sid alone.
export type SessionState = SessionSummary;

export interface VerifyAugmentationResp {
  found: boolean;
  size: number;
  preview: string;
}

export interface ModelContextResp {
  context_window: number | null;
}
