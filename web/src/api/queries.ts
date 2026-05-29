import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as t from "./types";
import {
  apiGet, apiPostJson, apiPut, apiPostRawYaml, apiDelete, apiPatch,
} from "./client";

export const qk = {
  experiments: ["experiments"] as const,
  experiment: (name: string) => ["experiment", name] as const,
  runs: (name: string) => ["runs", name] as const,
  trace: (name: string, condition: string, rep: number) =>
    ["trace", name, condition, rep] as const,
  metrics: (name: string, condition: string, rep: number) =>
    ["metrics", name, condition, rep] as const,
  patch: (name: string, condition: string, rep: number) =>
    ["patch", name, condition, rep] as const,
  methodCmp: (name: string, condition: string, rep: number, method: string) =>
    ["methodCmp", name, condition, rep, method] as const,
  providers: ["providers"] as const,
  sessionState: (sid: string) => ["sessionState", sid] as const,
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

export const useRuns = (name: string | undefined) =>
  useQuery({
    queryKey: qk.runs(name ?? ""),
    enabled: Boolean(name),
    queryFn: () => apiGet<t.RunSummary[]>(`/api/runs/${name}`),
  });

export const useTrace = (name: string, condition: string, rep: number) =>
  useQuery({
    queryKey: qk.trace(name, condition, rep),
    queryFn: () => apiGet<t.Trace>(`/api/runs/${name}/${condition}/${rep}/trace`),
  });

export const useEvents = (name: string, condition: string, rep: number) =>
  useQuery({
    queryKey: ["events", name, condition, rep],
    queryFn: async () => {
      // Backend returns text/plain JSONL (one JSON per line).
      const text = await apiGet<string>(`/api/runs/${name}/${condition}/${rep}/events`);
      return text
        .split("\n")
        .filter((l) => l.trim().length > 0)
        .map((l) => JSON.parse(l));
    },
  });

export const useMetrics = (name: string, condition: string, rep: number) =>
  useQuery({
    queryKey: qk.metrics(name, condition, rep),
    queryFn: () => apiGet<t.MetricsJson>(`/api/runs/${name}/${condition}/${rep}/metrics`),
  });

export const usePatch = (name: string, condition: string, rep: number) =>
  useQuery({
    queryKey: qk.patch(name, condition, rep),
    queryFn: () => apiGet<string>(`/api/runs/${name}/${condition}/${rep}/patch`),
  });

export const useMethodComparison = (
  name: string, condition: string, rep: number, method: string | undefined,
) =>
  useQuery({
    queryKey: qk.methodCmp(name, condition, rep, method ?? ""),
    enabled: Boolean(method),
    queryFn: () => apiGet<t.MethodComparison>(
      `/api/runs/${name}/${condition}/${rep}/method_comparison?method=${encodeURIComponent(method!)}`,
    ),
  });

export function usePatchSuccess() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { name: string; condition: string; rep: number; success: boolean | null }) =>
      apiPatch<t.MetricsJson>(
        `/api/runs/${args.name}/${args.condition}/${args.rep}`,
        { success: args.success },
      ),
    onSuccess: (_d, a) => {
      qc.invalidateQueries({ queryKey: qk.metrics(a.name, a.condition, a.rep) });
      qc.invalidateQueries({ queryKey: qk.runs(a.name) });
    },
  });
}

export function useValidateModel() {
  return useMutation({
    mutationFn: (model: string) =>
      apiPostJson<t.ValidateModelResp>(`/api/validate/model`, { model }),
  });
}

export const useProviders = () =>
  useQuery({
    queryKey: qk.providers,
    queryFn: () => apiGet<t.ProviderEntry[]>(`/api/providers`),
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

export function useCancelSession() {
  return useMutation({
    mutationFn: (sid: string) => apiDelete<void>(`/api/sessions/${sid}`),
  });
}
