import { useParams } from "react-router-dom";
import { Stack, Typography, CircularProgress, Alert } from "@mui/material";
import { useTrace, useEvents } from "../api/queries";
import { groupEventsByTurn } from "../lib/groupEventsByTurn";
import VerdictBanner from "../components/VerdictBanner";
import AggregateStatsBar from "../components/AggregateStatsBar";
import TurnCard from "../components/TurnCard";
import VerifyCard from "../components/VerifyCard";
import FinalDiffCard from "../components/FinalDiffCard";
import MethodComparisonCard from "../components/MethodComparisonCard";
import MetricsDrawer from "../components/MetricsDrawer";
import FooterNav from "../components/FooterNav";

export default function TraceView() {
  const { name, condition, rep } = useParams<{ name: string; condition: string; rep: string }>();
  const repN = Number(rep);
  const trace = useTrace(name!, condition!, repN);
  const events = useEvents(name!, condition!, repN);

  if (trace.isLoading) return <CircularProgress />;
  if (trace.error || !trace.data) return <Alert severity="error">Failed to load trace.</Alert>;

  const groups = events.data ? groupEventsByTurn(events.data) : [];

  return (
    <Stack spacing={2} sx={{ maxWidth: 1100, mx: "auto" }}>
      <Typography variant="h5">{name} / {condition} / rep {repN}</Typography>
      <VerdictBanner trace={trace.data} />
      <AggregateStatsBar turns={trace.data.turns} />
      {trace.data.turns.map((t, i) => {
        const g = groups.find((gg) => gg.messageId === t.message_id);
        if (!g) return null;
        const raw = events.data?.filter((e: any) => e?.part?.messageID === t.message_id) ?? [];
        return <TurnCard key={t.message_id} turn={t} group={g} index={i} rawEvents={raw} />;
      })}
      <VerifyCard trace={trace.data} />
      <FinalDiffCard name={name!} condition={condition!} rep={repN} />
      <MethodComparisonCard name={name!} condition={condition!} rep={repN} />
      <FooterNav name={name!} condition={condition!} rep={repN} />
      <MetricsDrawer name={name!} condition={condition!} rep={repN} />
    </Stack>
  );
}
