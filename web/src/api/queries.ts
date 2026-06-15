import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as t from "./types";
import {
  apiGet, apiPostJson, apiPut, apiPostRawYaml, apiDelete, apiPatch,
} from "./client";

// Batch is a UTC timestamp id (or "legacy"); "" means "newest" (no ?batch=).
const b = (batch?: string) => batch ?? "";

// Append ?batch=<id> when a batch is selected; otherwise leave the URL alone
// so behaviour is identical to before (server returns the newest batch).
const withBatch = (url: string, batch?: string) =>
  batch ? `${url}?batch=${encodeURIComponent(batch)}` : url;

export const qk = {
  experiments: ["experiments"] as const,
  experiment: (name: string) => ["experiment", name] as const,
  batches: (name: string) => ["batches", name] as const,
  runs: (name: string, batch?: string) => ["runs", name, b(batch)] as const,
  runsSummary: (name: string, batch?: string) =>
    ["runsSummary", name, b(batch)] as const,
  trace: (name: string, condition: string, rep: number, batch?: string) =>
    ["trace", name, condition, rep, b(batch)] as const,
  metrics: (name: string, condition: string, rep: number, batch?: string) =>
    ["metrics", name, condition, rep, b(batch)] as const,
  patch: (name: string, condition: string, rep: number, batch?: string) =>
    ["patch", name, condition, rep, b(batch)] as const,
  methodCmp: (name: string, condition: string, rep: number, method: string, batch?: string) =>
    ["methodCmp", name, condition, rep, method, b(batch)] as const,
  verifyLog: (name: string, condition: string, rep: number, batch?: string) =>
    ["verifyLog", name, condition, rep, b(batch)] as const,
  runLog: (name: string, condition: string, rep: number, batch?: string) =>
    ["runLog", name, condition, rep, b(batch)] as const,
  detectedVerify: (name: string) => ["detectedVerify", name] as const,
  verifyJob: (id: string) => ["verifyJob", id] as const,
  providers: ["providers"] as const,
  sessionState: (sid: string) => ["sessionState", sid] as const,
  activeSessions: ["activeSessions"] as const,
};

export const useExperiments = () =>
  useQuery({
    queryKey: qk.experiments,
    queryFn: () => apiGet<t.ExperimentSummary[]>("/api/experiments"),
  });

export const useExperiment = (name: string | undefined) =>
  useQuery({
    queryKey: qk.experiment(name ?? ""),
    enabled: Boolean(name),
    queryFn: () => apiGet<Record<string, unknown>>(`/api/experiments/${name}`),
  });

export function useSaveExperiment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, body }: { name: string; body: Record<string, unknown> }) =>
      apiPut<void>(`/api/experiments/${name}`, body),
    onSuccess: (_d, { name }) => {
      qc.invalidateQueries({ queryKey: qk.experiment(name) });
      qc.invalidateQueries({ queryKey: qk.experiments });
    },
  });
}

export function useDeleteExperiment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => apiDelete<void>(`/api/experiments/${name}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.experiments }),
  });
}

export function useUploadExperiment() {
  return useMutation({
    mutationFn: (yaml: string) =>
      apiPostRawYaml<Record<string, unknown>>(`/api/experiments/upload`, yaml),
  });
}

export const useBatches = (name: string | undefined) =>
  useQuery({
    queryKey: qk.batches(name ?? ""),
    enabled: Boolean(name),
    // Server returns batches newest-first; a legacy flat layout surfaces as a
    // single {id:"legacy", ...}.
    queryFn: () => apiGet<t.RunBatch[]>(`/api/runs/${name}/batches`),
  });

export const useRuns = (
  name: string | undefined,
  batch?: string,
  opts?: { refetchInterval?: number | false },
) =>
  useQuery({
    queryKey: qk.runs(name ?? "", batch),
    enabled: Boolean(name),
    queryFn: () => apiGet<t.RunSummary[]>(withBatch(`/api/runs/${name}`, batch)),
    refetchInterval: opts?.refetchInterval,
  });

export const useRunsSummary = (name: string | undefined, batch?: string) =>
  useQuery({
    queryKey: qk.runsSummary(name ?? "", batch),
    enabled: Boolean(name),
    queryFn: () => apiGet<t.RunsSummary>(withBatch(`/api/runs/${name}/summary`, batch)),
  });

export const useTrace = (name: string, condition: string, rep: number, batch?: string) =>
  useQuery({
    queryKey: qk.trace(name, condition, rep, batch),
    queryFn: () =>
      apiGet<t.Trace>(withBatch(`/api/runs/${name}/${condition}/${rep}/trace`, batch)),
  });

export const useEvents = (name: string, condition: string, rep: number, batch?: string) =>
  useQuery({
    queryKey: ["events", name, condition, rep, b(batch)],
    queryFn: async () => {
      // Backend returns text/plain JSONL (one JSON per line).
      const text = await apiGet<string>(
        withBatch(`/api/runs/${name}/${condition}/${rep}/events`, batch),
      );
      return text
        .split("\n")
        .filter((l) => l.trim().length > 0)
        .map((l) => JSON.parse(l));
    },
  });

export const useMetrics = (name: string, condition: string, rep: number, batch?: string) =>
  useQuery({
    queryKey: qk.metrics(name, condition, rep, batch),
    queryFn: () =>
      apiGet<t.MetricsJson>(withBatch(`/api/runs/${name}/${condition}/${rep}/metrics`, batch)),
  });

export const usePatch = (name: string, condition: string, rep: number, batch?: string) =>
  useQuery({
    queryKey: qk.patch(name, condition, rep, batch),
    queryFn: () =>
      apiGet<string>(withBatch(`/api/runs/${name}/${condition}/${rep}/patch`, batch)),
  });

export const useVerifyLog = (
  name: string, condition: string, rep: number, enabled: boolean, batch?: string,
) =>
  useQuery({
    queryKey: qk.verifyLog(name, condition, rep, batch),
    enabled,
    queryFn: () =>
      apiGet<string>(withBatch(`/api/runs/${name}/${condition}/${rep}/verify_log`, batch)),
  });

// Two per-run logs: "readable" (run.log — stages, tool/llm one-liners, results)
// is the default; "full" (debug.log — readable lines + opencode's verbose
// stderr) is opt-in. Cap what the viewer pulls + renders: a verbose log can be
// many MB and rendering it all freezes the browser. We fetch only the tail; the
// full file stays available via logUrl() (download).
export const RUN_LOG_TAIL_CHARS = 200_000;

export type LogKind = "readable" | "full";
const LOG_ENDPOINT: Record<LogKind, string> = {
  readable: "run_log",
  full: "debug_log",
};

export function logUrl(
  name: string, condition: string, rep: number, kind: LogKind, batch?: string,
): string {
  return withBatch(
    `/api/runs/${name}/${condition}/${rep}/${LOG_ENDPOINT[kind]}`, batch);
}

export const useRunLog = (
  name: string, condition: string, rep: number, enabled: boolean,
  batch?: string, kind: LogKind = "readable",
) =>
  useQuery({
    queryKey: [...qk.runLog(name, condition, rep, batch), kind],
    enabled,
    queryFn: () => {
      const ep = LOG_ENDPOINT[kind];
      const base = `/api/runs/${name}/${condition}/${rep}/${ep}?tail_bytes=${RUN_LOG_TAIL_CHARS}`;
      const url = batch ? `${base}&batch=${encodeURIComponent(batch)}` : base;
      return apiGet<string>(url);
    },
  });

export const useDetectedVerify = (name: string | undefined) =>
  useQuery({
    queryKey: qk.detectedVerify(name ?? ""),
    enabled: Boolean(name),
    queryFn: () => apiGet<t.DetectedVerify>(`/api/experiments/${name}/verify_command`),
  });

export function useStartReverify() {
  return useMutation({
    mutationFn: (args: {
      name: string; condition?: string; rep?: number; batch?: string;
    }) =>
      apiPostJson<{ verify_id: string }>(`/api/verify`, args),
  });
}

// Recompute metrics for a batch from stored trace.json (no agent re-run) — picks
// up metric changes (tests_executed, token totals) for past runs.
export function useRecomputeMetrics() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { name: string; batch?: string }) =>
      apiPostJson<{ recomputed: number }>(
        withBatch(`/api/runs/${args.name}/recompute`, args.batch), {}),
    onSuccess: (_data, args) => {
      qc.invalidateQueries({ queryKey: ["runs", args.name] });
      qc.invalidateQueries({ queryKey: ["runsSummary", args.name] });
    },
  });
}

export const useReverifyStatus = (verifyId: string | null) =>
  useQuery({
    queryKey: qk.verifyJob(verifyId ?? ""),
    enabled: Boolean(verifyId),
    queryFn: () => apiGet<t.ReverifyJob>(`/api/verify/${verifyId}`),
    refetchInterval: (q) =>
      q.state.data && q.state.data.state === "running" ? 1000 : false,
  });

export const useMethodComparison = (
  name: string, condition: string, rep: number, method: string | undefined,
  batch?: string,
) =>
  useQuery({
    queryKey: qk.methodCmp(name, condition, rep, method ?? "", batch),
    enabled: Boolean(method),
    queryFn: () => apiGet<t.MethodComparison>(
      `/api/runs/${name}/${condition}/${rep}/method_comparison?method=${encodeURIComponent(method!)}`
      + (batch ? `&batch=${encodeURIComponent(batch)}` : ""),
    ),
  });

export function usePatchSuccess() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: {
      name: string; condition: string; rep: number; success: boolean | null; batch?: string;
    }) =>
      apiPatch<t.MetricsJson>(
        withBatch(`/api/runs/${args.name}/${args.condition}/${args.rep}`, args.batch),
        { success: args.success },
      ),
    onSuccess: (_d, a) => {
      // Invalidate by prefix so both newest ("") and the specific batch refetch.
      qc.invalidateQueries({ queryKey: ["metrics", a.name, a.condition, a.rep] });
      qc.invalidateQueries({ queryKey: ["runs", a.name] });
      qc.invalidateQueries({ queryKey: ["runsSummary", a.name] });
    },
  });
}

export function useValidateModel() {
  return useMutation({
    mutationFn: (model: string) =>
      apiPostJson<t.ValidateModelResp>(`/api/validate/model`, { model }),
  });
}

// Real reachability probe (POST /api/validate/reachability): runs a 1-token
// probe of the configured endpoint INSIDE the experiment's sandbox. Operates on
// the SAVED experiment (the server loads experiment.yaml by name).
export function useValidateReachability() {
  return useMutation({
    mutationFn: (experiment_name: string) =>
      apiPostJson<t.ValidateReachabilityResp>(
        `/api/validate/reachability`, { experiment_name }),
  });
}

export const useProviders = () =>
  useQuery({
    queryKey: qk.providers,
    queryFn: () => apiGet<t.ProviderEntry[]>(`/api/providers`),
  });

export const useModelCatalog = () =>
  useQuery({
    queryKey: ["modelCatalog"],
    queryFn: () => apiGet<t.ModelCatalogEntry[]>("/api/models"),
    staleTime: 5 * 60_000,
  });

export function useWriteProviderCredentials() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { provider: string; api_key: string }) =>
      apiPostJson<void>(`/api/providers/${args.provider}/credentials`,
        { api_key: args.api_key }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.providers }),
  });
}

export function useStartRun() {
  return useMutation({
    mutationFn: (experiment_name: string) =>
      apiPostJson<{ session_id: string }>(`/api/runs`, { experiment_name }),
  });
}

export const useSessionState = (sid: string | undefined) =>
  useQuery({
    queryKey: qk.sessionState(sid ?? ""),
    enabled: Boolean(sid),
    queryFn: () => apiGet<t.SessionState>(`/api/sessions/${sid}`),
    refetchInterval: 2000,
  });

// In-flight sessions (pending/running). Polled so the "resume live run" banner
// appears/updates as runs start and finish.
export const useActiveSessions = () =>
  useQuery({
    queryKey: qk.activeSessions,
    queryFn: () => apiGet<t.SessionSummary[]>("/api/sessions"),
    refetchInterval: 3000,
  });

export function useCancelSession() {
  return useMutation({
    mutationFn: (sid: string) => apiDelete<void>(`/api/sessions/${sid}`),
  });
}
