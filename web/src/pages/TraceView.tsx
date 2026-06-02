import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Stack, Typography, CircularProgress, Alert, Box } from "@mui/material";
import { useTrace, useEvents, useRuns, useMetrics } from "../api/queries";
import { turnsFromTrace } from "../lib/traceModel";
import VerdictBanner from "../components/VerdictBanner";
import AggregateStatsBar from "../components/AggregateStatsBar";
import TurnCard from "../components/TurnCard";
import VerifyCard from "../components/VerifyCard";
import FinalDiffCard from "../components/FinalDiffCard";
import MethodComparisonCard from "../components/MethodComparisonCard";
import MetricsDrawer from "../components/MetricsDrawer";
import TraceRunSwitcher from "../components/TraceRunSwitcher";

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
        <Typography variant="h5">{name} / {condition} / rep {repN}</Typography>
        <VerdictBanner trace={trace.data} />
        {trace.data.verify_baseline_unknown && (
          <Alert severity="warning">
            The reference project itself does not pass verify (build/environment issue) —
            run verdicts may be unreliable.
          </Alert>
        )}
        {metrics.data && <AggregateStatsBar metrics={metrics.data} />}
        {uiTurns.map((t) => (
          <TurnCard key={t.messageId ?? t.index} turn={t} index={t.index} rawEvents={rawByMsg(t.messageId)} />
        ))}
        <VerifyCard trace={trace.data} name={name!} condition={condition!} rep={repN} batch={batch} />
        <FinalDiffCard name={name!} condition={condition!} rep={repN} batch={batch} />
        <MethodComparisonCard name={name!} condition={condition!} rep={repN} batch={batch} />
        <MetricsDrawer name={name!} condition={condition!} rep={repN} batch={batch} />
      </Stack>
    </Stack>
  );
}
