import { useState } from "react";
import { Card, CardContent, Stack, Typography, Chip, Box, Button } from "@mui/material";
import RawEventsToggle from "./RawEventsToggle";
import { formatTokens } from "../lib/formatTokens";
import { selectable } from "../theme";
import { toolBreakdown, type UiTurn } from "../lib/traceModel";

interface Props { turn: UiTurn; index: number; rawEvents: unknown[]; }

const COLLAPSE = 600;

function argSummary(args: Record<string, unknown>): string {
  for (const k of ["command", "filePath", "path", "pattern", "query"]) {
    const v = args[k];
    if (typeof v === "string") return v.slice(0, 160);
  }
  const j = JSON.stringify(args);
  return j === "{}" ? "" : j.slice(0, 160);
}

function Long({ text, prefix, accent }: { text: string; prefix: string; accent: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > COLLAPSE;
  const shown = open || !long ? text : text.slice(0, COLLAPSE) + "…";
  return (
    <Box sx={{ borderLeft: 2, borderColor: accent, pl: 1.5, py: 0.25 }}>
      <Typography variant="body2" sx={{ whiteSpace: "pre-wrap", ...selectable }}>{prefix} {shown}</Typography>
      {long && <Button size="small" onClick={() => setOpen(!open)} sx={{ mt: 0.25 }}>{open ? "show less" : "show more"}</Button>}
    </Box>
  );
}

export default function TurnCard({ turn, index, rawEvents }: Props) {
  const breakdown = toolBreakdown(turn);
  const breakdownStr = Object.entries(breakdown).map(([n, c]) => `${n} ×${c}`).join(" · ") || "no tools";
  return (
    <Card variant="outlined">
      <CardContent>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }} flexWrap="wrap">
          <Chip size="small" variant="outlined" label={`turn ${index + 1}`} />
          {turn.reason && <Chip size="small" color="primary" label={turn.reason} />}
          <Box sx={{ flexGrow: 1 }} />
          <Typography variant="caption" color="text.secondary">
            in {formatTokens(turn.tokensIn)} · out {formatTokens(turn.tokensOut)}
            {turn.cost != null && <> · ${turn.cost.toFixed(4)}</>}
            {turn.durationS != null && <> · {turn.durationS.toFixed(1)}s</>}
          </Typography>
        </Stack>

        <Stack spacing={1.25}>
          {turn.parts.map((p, i) => {
            if (p.kind === "reasoning") return <Long key={i} prefix="💭" accent="info.main" text={p.text} />;
            if (p.kind === "text") return <Long key={i} prefix="🗨" accent="text.primary" text={p.text} />;
            if (p.kind === "edit") return (
              <Box key={i} sx={{ borderLeft: 2, borderColor: "warning.main", pl: 1.5 }}>
                <Typography variant="body2" sx={selectable}><b>📝 {p.path}</b></Typography>
                <Typography variant="caption" component="pre" sx={{ m: 0, whiteSpace: "pre-wrap", ...selectable }}>
                  {p.patch.slice(0, 400)}
                </Typography>
              </Box>
            );
            if (p.kind === "tool") return (
              <Box key={i} sx={{ borderLeft: 2, borderColor: p.ok === false ? "error.main" : "success.main", pl: 1.5, ...selectable }}>
                <Typography variant="body2">
                  <b>{p.ok === false ? "✗" : p.ok ? "✓" : "✎"} {p.name}</b> {argSummary(p.args)}
                  {p.exitCode != null && p.exitCode !== 0 && <> · exit {p.exitCode}</>}
                </Typography>
                {p.output && (
                  <Typography variant="caption" color="text.secondary" sx={{ whiteSpace: "pre-wrap", ...selectable }}>
                    → {p.output.slice(0, 300)}
                  </Typography>
                )}
              </Box>
            );
            return null;
          })}
        </Stack>

        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1.5 }}>
          {breakdownStr}
        </Typography>
        <RawEventsToggle events={rawEvents} />
      </CardContent>
    </Card>
  );
}
