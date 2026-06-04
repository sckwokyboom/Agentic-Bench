import { Card, CardContent, Typography, Stack, Link } from "@mui/material";
import ScheduleIcon from "@mui/icons-material/Schedule";
import { Link as RouterLink } from "react-router-dom";
import { useRuns } from "../api/queries";
import { priorEstimateFromRuns, formatEta } from "../lib/eta";

interface Props { name: string; }

export default function PreviousRunsPanel({ name }: Props) {
  const runs = useRuns(name);
  const items = (runs.data ?? []).slice(-5).reverse();
  // Pre-run estimate: how long the last batch took, as a hint before Run.
  const prior = priorEstimateFromRuns(runs.data);
  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="subtitle2" gutterBottom>Previous runs</Typography>
        {prior && (
          <Typography
            variant="body2"
            color="text.secondary"
            sx={{ display: "flex", alignItems: "center", gap: 0.5, mb: 0.5 }}
          >
            <ScheduleIcon fontSize="small" /> last batch ≈ {formatEta(prior.totalSeconds)} for {prior.n} runs
          </Typography>
        )}
        {items.length === 0 && <Typography variant="body2">No runs yet.</Typography>}
        <Stack spacing={0.5}>
          {items.map((r) => (
            <Link
              key={`${r.condition}-${r.rep}`}
              component={RouterLink}
              to={`/runs/${name}/${r.condition}/${r.rep}`}
              variant="body2"
            >
              {r.condition} / rep {r.rep} — {r.verify_status ?? "—"}
            </Link>
          ))}
        </Stack>
      </CardContent>
    </Card>
  );
}
