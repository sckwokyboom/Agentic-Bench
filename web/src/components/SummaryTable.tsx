import { useState } from "react";
import {
  Table, TableHead, TableBody, TableRow, TableCell, Typography, Box, Tooltip,
  FormControl, InputLabel, Select, MenuItem,
} from "@mui/material";
import { selectable } from "../theme";
import { SUMMARY_METRICS } from "../lib/metricLabels";
import type { RunsSummary } from "../api/types";

interface Props { summary: RunsSummary; }

function fmt(v: number | null | undefined): string {
  return v == null ? "—" : v.toFixed(2);
}

export default function SummaryTable({ summary }: Props) {
  const conditions = summary.conditions;
  // Treatment to diff against baseline is user-selectable (was hardcoded to
  // "augmented"). Default to "augmented" if present, else the first
  // non-baseline condition. `picked` falls back to the default if it names a
  // condition absent from the current summary (e.g. after a batch switch).
  const base = conditions.find((c) => c.name === "baseline");
  const treatments = conditions.filter((c) => c.name !== "baseline");
  const defaultTreat =
    treatments.find((c) => c.name === "augmented")?.name ?? treatments[0]?.name ?? "";
  const [picked, setPicked] = useState<string | null>(null);
  const treatName =
    picked && treatments.some((c) => c.name === picked) ? picked : defaultTreat;
  const treat = conditions.find((c) => c.name === treatName);

  if (conditions.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        No aggregate yet — runs may be in progress or all interrupted.
      </Typography>
    );
  }

  const hasDelta = Boolean(base && treat && treat.name !== base.name);

  // Relative % change of the selected treatment vs baseline, matching the
  // backend (report.py): (treat - base) / base * 100, guarded against a
  // missing/zero baseline. Computed client-side from each condition's own
  // metrics so ANY treatment can be diffed without a re-fetch.
  function pctDelta(key: string): number | null {
    const b = base?.metrics[key]?.mean;
    const t = treat?.metrics[key]?.mean;
    if (b == null || t == null || b === 0) return null;
    return ((t - b) / b) * 100;
  }
  // success_rate / tests_pass_rate are higher-is-better rates → percentage-POINT
  // diffs, green when up.
  const srDeltaPP =
    base?.success_rate != null && treat?.success_rate != null
      ? (treat.success_rate - base.success_rate) * 100
      : null;
  const anyTpr = conditions.some((c) => c.tests_pass_rate != null);
  const tprDeltaPP =
    base?.tests_pass_rate != null && treat?.tests_pass_rate != null
      ? (treat.tests_pass_rate - base.tests_pass_rate) * 100
      : null;

  return (
    <>
      {hasDelta && treatments.length > 1 && (
        <FormControl size="small" sx={{ minWidth: 220, mb: 1 }}>
          <InputLabel id="delta-treat-label">Δ vs baseline</InputLabel>
          <Select
            labelId="delta-treat-label"
            label="Δ vs baseline"
            value={treatName}
            onChange={(e) => setPicked(e.target.value)}
          >
            {treatments.map((c) => (
              <MenuItem key={c.name} value={c.name}>{c.name}</MenuItem>
            ))}
          </Select>
        </FormControl>
      )}
      <Box sx={{ border: 1, borderColor: "divider", borderRadius: 1, overflow: "auto" }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>metric</TableCell>
              {conditions.map((c) => (
                <TableCell key={c.name} align="right">{c.name} (n={c.runs})</TableCell>
              ))}
              {hasDelta && <TableCell align="right">Δ {treatName} vs base</TableCell>}
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
            {anyTpr && (
              <TableRow hover>
                <TableCell>
                  <Tooltip title="Share of tests passing at the end across the condition's runs (Σpassed / Σ(passed+failed)) — surfaces near-misses like 2198/2200 that a binary success rate hides. Floored, so anything below a perfect pass reads under 100%.">
                    <span>tests passed %</span>
                  </Tooltip>
                </TableCell>
                {conditions.map((c) => (
                  <TableCell key={c.name} align="right" sx={selectable}>
                    {c.tests_pass_rate == null
                      ? "—"
                      : c.tests_pass_rate >= 1
                        ? "100%"
                        : `${(Math.floor(c.tests_pass_rate * 1000) / 10).toFixed(1)}%`}
                  </TableCell>
                ))}
                {hasDelta && (
                  <TableCell
                    align="right"
                    sx={{ color: tprDeltaPP == null || tprDeltaPP === 0 ? "text.secondary" : tprDeltaPP > 0 ? "success.main" : "error.main" }}
                  >
                    {tprDeltaPP == null ? "—" : `${tprDeltaPP > 0 ? "+" : ""}${tprDeltaPP.toFixed(1)}pp`}
                  </TableCell>
                )}
              </TableRow>
            )}
            {SUMMARY_METRICS.map((m) => {
              const delta = pctDelta(m.key);
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
    </>
  );
}
