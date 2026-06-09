import { useState, type ReactNode } from "react";
import { Card, CardContent, Stack, Typography, Chip, Box, Button } from "@mui/material";
import PsychologyOutlinedIcon from "@mui/icons-material/PsychologyOutlined";
import ChatBubbleOutlineIcon from "@mui/icons-material/ChatBubbleOutline";
import EditNoteIcon from "@mui/icons-material/EditNote";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import CancelIcon from "@mui/icons-material/Cancel";
import PendingOutlinedIcon from "@mui/icons-material/PendingOutlined";
import RawEventsToggle from "./RawEventsToggle";
import { formatTokens } from "../lib/formatTokens";
import { selectable } from "../theme";
import { toolBreakdown, turnObsTokens, type UiPart, type UiTurn } from "../lib/traceModel";

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

// Inline glyph rendered before a Typography's text: inherits the font size and
// sits on the text baseline so it reads as a leading marker, not a standalone icon.
const inlineIcon = { fontSize: "inherit", verticalAlign: "middle", mr: 0.5 } as const;

function Long({ text, prefix, accent }: { text: string; prefix: ReactNode; accent: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > COLLAPSE;
  const shown = open || !long ? text : text.slice(0, COLLAPSE) + "…";
  return (
    <Box sx={{ borderLeft: 2, borderColor: accent, pl: 1.5, py: 0.25 }}>
      <Typography variant="body2" sx={{ whiteSpace: "pre-wrap", ...selectable }}>{prefix}{shown}</Typography>
      {long && <Button size="small" onClick={() => setOpen(!open)} sx={{ mt: 0.25 }}>{open ? "show less" : "show more"}</Button>}
    </Box>
  );
}

// A tool call + its result. The result (observation) is what the model reads back
// into context, so it's expandable and labelled with its estimated token cost.
function ToolPart({ p }: { p: Extract<UiPart, { kind: "tool" }> }) {
  const [open, setOpen] = useState(false);
  const out = p.output ?? "";
  const long = out.length > COLLAPSE;
  const shown = open || !long ? out : out.slice(0, COLLAPSE) + "…";
  return (
    <Box sx={{ borderLeft: 2, borderColor: p.ok === false ? "error.main" : "success.main", pl: 1.5, ...selectable }}>
      <Typography variant="body2">
        <b>
          {p.ok === false
            ? <CancelIcon color="error" sx={inlineIcon} />
            : p.ok
              ? <CheckCircleIcon color="success" sx={inlineIcon} />
              : <PendingOutlinedIcon color="disabled" sx={inlineIcon} />}
          {p.name}
        </b> {argSummary(p.args)}
        {p.exitCode != null && p.exitCode !== 0 && <> · exit {p.exitCode}</>}
        {p.outputTokens > 0 && (
          <Typography component="span" variant="caption" color="text.secondary">
            {" · ≈"}{formatTokens(p.outputTokens)} tok ctx
          </Typography>
        )}
      </Typography>
      {p.output && (
        <Typography variant="caption" color="text.secondary" component="div"
          sx={{ whiteSpace: "pre-wrap", ...selectable }}>
          → {shown}
          {long && (
            <Button size="small" onClick={() => setOpen(!open)} sx={{ ml: 0.5, py: 0, minWidth: 0 }}>
              {open ? "show less" : "show more"}
            </Button>
          )}
        </Typography>
      )}
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
            {turnObsTokens(turn) > 0 && <> · obs ≈{formatTokens(turnObsTokens(turn))}</>}
            {turn.cost != null && <> · ${turn.cost.toFixed(4)}</>}
            {turn.durationS != null && <> · {turn.durationS.toFixed(1)}s</>}
          </Typography>
        </Stack>

        <Stack spacing={1.25}>
          {turn.parts.map((p, i) => {
            if (p.kind === "reasoning") return <Long key={i} prefix={<PsychologyOutlinedIcon color="info" sx={inlineIcon} />} accent="info.main" text={p.text} />;
            if (p.kind === "text") return <Long key={i} prefix={<ChatBubbleOutlineIcon sx={{ ...inlineIcon, color: "text.primary" }} />} accent="text.primary" text={p.text} />;
            if (p.kind === "edit") return (
              <Box key={i} sx={{ borderLeft: 2, borderColor: "warning.main", pl: 1.5 }}>
                <Typography variant="body2" sx={selectable}>
                  <b><EditNoteIcon color="warning" sx={inlineIcon} />{p.path}</b>
                </Typography>
                <Typography variant="caption" component="pre" sx={{ m: 0, whiteSpace: "pre-wrap", ...selectable }}>
                  {p.patch.slice(0, 400)}
                </Typography>
              </Box>
            );
            if (p.kind === "tool") return <ToolPart key={i} p={p} />;
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
