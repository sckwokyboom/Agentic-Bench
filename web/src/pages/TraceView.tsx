import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Stack, Typography, CircularProgress, Alert, Box } from "@mui/material";
import { useTrace, useEvents, useRuns, useMetrics } from "../api/queries";
import {
  turnsFromTrace, observationTokensByTool, observationTokensTotal, realInputTokensTotal,
} from "../lib/traceModel";
import { formatTokens } from "../lib/formatTokens";
import VerdictBanner from "../components/VerdictBanner";
import ValiditySignals from "../components/ValiditySignals";
import AggregateStatsBar from "../components/AggregateStatsBar";
import TurnCard from "../components/TurnCard";
import VerifyCard from "../components/VerifyCard";
import FinalDiffCard from "../components/FinalDiffCard";
import RunLogToggle from "../components/RunLogToggle";
import MethodComparisonCard from "../components/MethodComparisonCard";
import MetricsDrawer from "../components/MetricsDrawer";
import TraceRunSwitcher from "../components/TraceRunSwitcher";
import SafeTraceButton from "../components/SafeTraceButton";

export default function TraceView() {
  const { name, condition, rep } = useParams<{ name: string; condition: string; rep: string }>();
  const navigate = useNavigate();
  const [sp] = useSearchParams();
  // Batch is a search param, not a path segment; undefined → server's newest.
  const batch = sp.get("batch") ?? undefined;
  const batchQs = batch ? `?batch=${encodeURIComponent(batch)}` : "";
  const repN = Number(rep);
  const trace = useTrace(name!, condition!, repN, batch);
  const events = useEvents(name!, condition!, repN, batch);
  const metrics = useMetrics(name!, condition!, repN, batch);
  const runs = useRuns(name, batch);

  if (trace.isLoading) return <CircularProgress />;
  if (trace.error || !trace.data) return <Alert severity="error">Failed to load trace.</Alert>;

  const uiTurns = turnsFromTrace(trace.data);
  const rawByMsg = (mid: string | null) =>
    (events.data ?? []).filter((e: any) => e?.part?.messageID === mid);

  // How much context the agent's tool outputs poured in (estimate), and the real
  // provider input total for contrast (the gap ≈ what OpenCode compacted away).
  const obsByTool = observationTokensByTool(uiTurns);
  const obsTotal = observationTokensTotal(uiTurns);
  const realIn = realInputTokensTotal(uiTurns);
  const obsStr = Object.entries(obsByTool)
    .sort((a, b) => b[1] - a[1])
    .map(([n, v]) => `${n} ≈${formatTokens(v)}`)
    .join(" · ");

  // Validity signals: metrics is the authoritative source for counts/flags;
  // trace carries the human-readable service-error messages. `made_source_changes`
  // lives only on metrics — fall back to the trace's diff summary otherwise.
  const m = metrics.data;
  const nServiceErrors = m?.n_service_errors ?? trace.data.n_service_errors ?? 0;
  const verifyInsensitive = m?.verify_insensitive ?? trace.data.verify_insensitive ?? false;
  const interruptedReason = m?.interrupted_reason ?? null;
  const madeSourceChanges = m?.made_source_changes
    ?? ((trace.data.final_diff_summary?.files?.length ?? 0) > 0);

  return (
    <Stack direction="row" spacing={3} sx={{ maxWidth: 1280, mx: "auto", alignItems: "flex-start" }}>
      <Box sx={{ position: "sticky", top: 0, alignSelf: "flex-start", flexShrink: 0 }}>
        {runs.data && (
          <TraceRunSwitcher
            rows={runs.data}
            current={{ condition: condition!, rep: repN }}
            onSelect={(c, r) => navigate(`/runs/${name}/${c}/${r}${batchQs}`)}
          />
        )}
      </Box>

      <Stack spacing={2} sx={{ flex: 1, minWidth: 0 }}>
        <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between">
          <Typography variant="h5">{name} / {condition} / rep {repN}</Typography>
          <SafeTraceButton name={name!} condition={condition!} rep={repN} batch={batch} />
        </Stack>
        <ValiditySignals
          nServiceErrors={nServiceErrors}
          interruptedReason={interruptedReason}
          serviceErrorMessages={trace.data.service_error_messages}
          verifyInsensitive={verifyInsensitive}
          cheating={m?.cheating}
        />
        <VerdictBanner trace={trace.data} />
        {trace.data.verify_baseline_unknown && (
          <Alert severity="warning">
            The reference project itself does not pass verify (build/environment issue) —
            run verdicts may be unreliable.
          </Alert>
        )}
        {metrics.data && <AggregateStatsBar metrics={metrics.data} />}
        {obsTotal > 0 && (
          <Typography variant="caption" color="text.secondary">
            Context from tool outputs: ≈{formatTokens(obsTotal)} tok ({obsStr}) · real Σ input {formatTokens(realIn)}
          </Typography>
        )}
        {uiTurns.map((t) => (
          <TurnCard key={t.messageId ?? t.index} turn={t} index={t.index} rawEvents={rawByMsg(t.messageId)} />
        ))}
        <VerifyCard trace={trace.data} name={name!} condition={condition!} rep={repN} batch={batch} />
        <FinalDiffCard
          name={name!} condition={condition!} rep={repN} batch={batch}
          madeSourceChanges={madeSourceChanges}
        />
        <MethodComparisonCard name={name!} condition={condition!} rep={repN} batch={batch} />
        <RunLogToggle name={name!} condition={condition!} rep={repN} batch={batch} />
        <MetricsDrawer name={name!} condition={condition!} rep={repN} batch={batch} />
      </Stack>
    </Stack>
  );
}
