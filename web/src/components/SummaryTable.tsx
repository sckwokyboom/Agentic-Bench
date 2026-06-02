import {
  Table, TableHead, TableBody, TableRow, TableCell, Typography, Box, Tooltip,
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

  // success_rate is a top-level per-condition field (not in metrics/deltas), and
  // higher is better — so its delta is a percentage-POINT diff, green when up.
  const base = conditions.find((c) => c.name === "baseline");
  const aug = conditions.find((c) => c.name === "augmented");
  const srDeltaPP =
    base?.success_rate != null && aug?.success_rate != null
      ? (aug.success_rate - base.success_rate) * 100
      : null;
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
          <TableRow hover>
            <TableCell>success rate</TableCell>
            {conditions.map((c) => (
              <TableCell key={c.name} align="right" sx={selectable}>
                {c.success_rate == null ? "—" : `${(c.success_rate * 100).toFixed(0)}%`}
              </TableCell>
            ))}
            {hasDelta && (
              <TableCell
                align="right"
                sx={{ color: srDeltaPP == null || srDeltaPP === 0 ? "text.secondary" : srDeltaPP > 0 ? "success.main" : "error.main" }}
              >
                {srDeltaPP == null ? "—" : `${srDeltaPP > 0 ? "+" : ""}${srDeltaPP.toFixed(0)}pp`}
              </TableCell>
            )}
          </TableRow>
          {SUMMARY_METRICS.map((m) => {
            const delta = summary.deltas[m.key];
            const good = delta != null && delta !== 0 &&
              (m.direction === "lower" ? delta < 0 : m.direction === "higher" ? delta > 0 : false);
            const bad = delta != null && delta !== 0 && m.direction !== "neutral" && !good;
            return (
              <TableRow key={m.key} hover>
                <TableCell>
                  {m.help
                    ? <Tooltip title={m.help}><span>{m.label}</span></Tooltip>
                    : m.label}
                </TableCell>
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
