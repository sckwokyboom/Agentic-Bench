import { Stack, Button, Typography } from "@mui/material";
import { Link as RouterLink } from "react-router-dom";
import { useRuns } from "../api/queries";

interface Props {
  name: string;
  condition: string;
  rep: number;
}

export default function FooterNav({ name, condition, rep }: Props) {
  const runs = useRuns(name);
  if (!runs.data) return null;
  const ordered = [...runs.data].sort(
    (a, b) => a.condition.localeCompare(b.condition) || a.rep - b.rep,
  );
  const idx = ordered.findIndex((r) => r.condition === condition && r.rep === rep);
  const prev = idx > 0 ? ordered[idx - 1] ?? null : null;
  const next = idx >= 0 && idx < ordered.length - 1 ? ordered[idx + 1] ?? null : null;
  return (
    <Stack direction="row" alignItems="center" spacing={2} sx={{ mt: 4 }}>
      {prev
        ? <Button component={RouterLink} to={`/runs/${name}/${prev.condition}/${prev.rep}`}>
            ← {prev.condition}/rep {prev.rep}
          </Button>
        : <Button disabled>← prev</Button>}
      <Typography variant="body2" sx={{ flex: 1, textAlign: "center" }}>
        {idx + 1} / {ordered.length} runs
      </Typography>
      {next
        ? <Button component={RouterLink} to={`/runs/${name}/${next.condition}/${next.rep}`}>
            {next.condition}/rep {next.rep} →
          </Button>
        : <Button disabled>next →</Button>}
    </Stack>
  );
}
