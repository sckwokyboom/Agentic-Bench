import { Stack, Typography, List, ListItemButton, ListItemText, Box } from "@mui/material";
import VerifyStatusChip from "./VerifyStatusChip";
import type { RunSummary } from "../api/types";

interface Props {
  rows: RunSummary[];
  current: { condition: string; rep: number };
  onSelect: (condition: string, rep: number) => void;
}

export default function TraceRunSwitcher({ rows, current, onSelect }: Props) {
  const byCondition = new Map<string, RunSummary[]>();
  for (const r of rows) {
    const arr = byCondition.get(r.condition) ?? [];
    arr.push(r);
    byCondition.set(r.condition, arr);
  }
  return (
    <Box sx={{ width: 240 }}>
      <Typography variant="overline" color="text.secondary">Runs</Typography>
      <Stack spacing={1}>
        {[...byCondition.entries()].map(([cond, reps]) => (
          <Box key={cond}>
            <Typography variant="caption" color="text.secondary">{cond}</Typography>
            <List dense disablePadding>
              {reps.slice().sort((a, b) => a.rep - b.rep).map((r) => {
                const isCurrent = r.condition === current.condition && r.rep === current.rep;
                return (
                  <ListItemButton
                    key={`${r.condition}-${r.rep}`}
                    selected={isCurrent}
                    onClick={() => onSelect(r.condition, r.rep)}
                    aria-label={`${r.condition} · rep ${r.rep}`}
                  >
                    <ListItemText primary={`${r.condition} · rep ${r.rep}`} />
                    <VerifyStatusChip status={r.verify_status} />
                  </ListItemButton>
                );
              })}
            </List>
          </Box>
        ))}
      </Stack>
    </Box>
  );
}
