import { useState } from "react";
import { Card, CardContent, Stack, Typography, Chip, Box, Button } from "@mui/material";
import ToolCallBlock from "./ToolCallBlock";
import RawEventsToggle from "./RawEventsToggle";
import { formatTokens } from "../lib/formatTokens";
import { selectable } from "../theme";
import type { TurnInfo } from "../api/types";
import type { TurnGroup } from "../lib/groupEventsByTurn";

interface Props {
  turn: TurnInfo;
  group: TurnGroup;
  index: number;
  rawEvents: unknown[];
}

const COLLAPSE_CHARS = 600;

function roleAccent(type: string): string {
  if (type === "reasoning") return "info.main";
  if (type === "tool-call") return "primary.main";
  if (type === "tool-result") return "success.main";
  if (type === "error") return "error.main";
  return "text.primary";
}

function Collapsible({ text, icon, accent }: { text: string; icon: string; accent: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > COLLAPSE_CHARS;
  const shown = open || !long ? text : text.slice(0, COLLAPSE_CHARS) + "…";
  return (
    <Box sx={{ borderLeft: 2, borderColor: accent, pl: 1.5, py: 0.25 }}>
      <Typography variant="body2" sx={{ whiteSpace: "pre-wrap", ...selectable }}>
        {icon} {shown}
      </Typography>
      {long && (
        <Button size="small" onClick={() => setOpen(!open)} sx={{ mt: 0.25 }}>
          {open ? "show less" : "show more"}
        </Button>
      )}
    </Box>
  );
}

export default function TurnCard({ turn, group, index, rawEvents }: Props) {
  const calls = group.parts.filter((p) => p.type === "tool-call");
  const results = group.parts.filter((p) => p.type === "tool-result");
  const reads = calls.filter((c) => c.name === "read").length;
  const greps = calls.filter((c) => c.name === "grep" || c.name === "search").length;
  const edits = calls.filter((c) => c.name === "edit" || c.name === "write").length;
  const duration = turn.started_at != null && turn.ended_at != null
    ? (turn.ended_at - turn.started_at).toFixed(1) + "s"
    : "—";

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
          <Chip size="small" variant="outlined" label={`turn ${index + 1}`} />
          {turn.reason && <Chip size="small" color="primary" label={turn.reason} />}
          <Box sx={{ flexGrow: 1 }} />
          <Typography variant="caption" color="text.secondary">
            {formatTokens(turn.tokens_in)}/{formatTokens(turn.tokens_out)} tok · ${turn.cost?.toFixed(4) ?? "—"} · {duration}
          </Typography>
        </Stack>

        <Stack spacing={1.25}>
          {group.parts.map((p, i) => {
            if (p.type === "reasoning") {
              return <Collapsible key={i} icon="💭" accent={roleAccent("reasoning")} text={String(p.text ?? "")} />;
            }
            if (p.type === "tool-call") {
              const matched = results.find((r) => r.toolCallID === p.toolCallID || r.callID === p.callID);
              return <ToolCallBlock key={i} call={p} result={matched} />;
            }
            if (p.type === "text") {
              return <Collapsible key={i} icon="🗨" accent={roleAccent("text")} text={String(p.text ?? "")} />;
            }
            return null;
          })}
        </Stack>

        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1.5 }}>
          tools {calls.length} · reads {reads} · greps {greps} · edits {edits}
        </Typography>
        <RawEventsToggle events={rawEvents} />
      </CardContent>
    </Card>
  );
}
