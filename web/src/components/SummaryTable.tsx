import {
  Table, TableHead, TableBody, TableRow, TableCell, Typography, Box,
} from "@mui/material";
import { selectable } from "../theme";
import { SUMMARY_METRICS } from "../lib/metricLabels";
import type { RunsSummary } from "../api/types";

interface Props { summary: RunsSummary; }

function fmt(v: number | null | undefined): string {
  return v == null ? "—" : v.toFixed(2);
}

export default function SummaryTable({ summary }: Props) {
  if (summary.conditions.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        No aggregate yet — runs may be in progress or all interrupted.
      </Typography>
    );
  }
  const conditions = summary.conditions;
  const hasDelta = Object.keys(summary.deltas).length > 0;
  return (
    <Box sx={{ border: 1, borderColor: "divider", borderRadius: 1, overflow: "auto" }}>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>metric</TableCell>
            {conditions.map((c) => (
              <TableCell key={c.name} align="right">{c.name} (n={c.runs})</TableCell>
            ))}
            {hasDelta && <TableCell align="right">Δ aug vs base</TableCell>}
          </TableRow>
        </TableHead>
        <TableBody>
          {SUMMARY_METRICS.map((m) => {
            const delta = summary.deltas[m.key];
            const good = delta != null && (m.lowerIsBetter ? delta < 0 : delta > 0);
            const bad = delta != null && delta !== 0 && !good;
            return (
              <TableRow key={m.key} hover>
                <TableCell>{m.label}</TableCell>
                {conditions.map((c) => (
                  <TableCell key={c.name} align="right" sx={selectable}>
                    {fmt(c.metrics[m.key]?.mean)}
                  </TableCell>
                ))}
                {hasDelta && (
                  <TableCell
                    align="right"
                    sx={{ color: good ? "success.main" : bad ? "error.main" : "text.secondary" }}
                  >
                    {delta == null ? "—" : `${delta > 0 ? "+" : ""}${delta.toFixed(1)}%`}
                  </TableCell>
                )}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </Box>
  );
}
