import { Card, CardContent, Typography, Stack, Link } from "@mui/material";
import { Link as RouterLink } from "react-router-dom";
import { useRuns } from "../api/queries";

interface Props { name: string; }

export default function PreviousRunsPanel({ name }: Props) {
  const runs = useRuns(name);
  const items = (runs.data ?? []).slice(-5).reverse();
  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="subtitle2" gutterBottom>Previous runs</Typography>
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
