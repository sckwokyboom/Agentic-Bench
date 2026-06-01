import { useNavigate, useParams } from "react-router-dom";
import { Stack, Typography, CircularProgress, Alert, Box } from "@mui/material";
import { useTrace, useEvents, useRuns } from "../api/queries";
import { groupEventsByTurn } from "../lib/groupEventsByTurn";
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
  const repN = Number(rep);
  const trace = useTrace(name!, condition!, repN);
  const events = useEvents(name!, condition!, repN);
  const runs = useRuns(name);

  if (trace.isLoading) return <CircularProgress />;
  if (trace.error || !trace.data) return <Alert severity="error">Failed to load trace.</Alert>;

  const groups = events.data ? groupEventsByTurn(events.data) : [];

  return (
    <Stack direction="row" spacing={3} sx={{ maxWidth: 1280, mx: "auto", alignItems: "flex-start" }}>
      <Box sx={{ position: "sticky", top: 0, alignSelf: "flex-start", flexShrink: 0 }}>
        {runs.data && (
          <TraceRunSwitcher
            rows={runs.data}
            current={{ condition: condition!, rep: repN }}
            onSelect={(c, r) => navigate(`/runs/${name}/${c}/${r}`)}
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
        <AggregateStatsBar turns={trace.data.turns} />
        {trace.data.turns.map((t, i) => {
          const g = groups.find((gg) => gg.messageId === t.message_id);
          if (!g) return null;
          const raw = events.data?.filter((e: any) => e?.part?.messageID === t.message_id) ?? [];
          return <TurnCard key={t.message_id} turn={t} group={g} index={i} rawEvents={raw} />;
        })}
        <VerifyCard trace={trace.data} name={name!} condition={condition!} rep={repN} />
        <FinalDiffCard name={name!} condition={condition!} rep={repN} />
        <MethodComparisonCard name={name!} condition={condition!} rep={repN} />
        <MetricsDrawer name={name!} condition={condition!} rep={repN} />
      </Stack>
    </Stack>
  );
}
