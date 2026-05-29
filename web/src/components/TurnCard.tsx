import { Card, CardContent, Stack, Typography, Chip } from "@mui/material";
import ToolCallBlock from "./ToolCallBlock";
import RawEventsToggle from "./RawEventsToggle";
import { formatTokens } from "../lib/formatTokens";
import type { TurnInfo } from "../api/types";
import type { TurnGroup } from "../lib/groupEventsByTurn";

interface Props {
  turn: TurnInfo;
  group: TurnGroup;
  index: number;
  rawEvents: unknown[];
}

function shortDescription(group: TurnGroup): string {
  const reasoning = group.parts.find((p) => p.type === "reasoning");
  if (reasoning) return String(reasoning.text ?? "").slice(0, 120);
  const calls = group.parts.filter((p) => p.type === "tool-call");
  if (calls.length > 0) return `→ ${calls.length} tool call${calls.length > 1 ? "s" : ""}`;
  const text = group.parts.find((p) => p.type === "text");
  if (text) return String(text.text ?? "").slice(0, 120);
  return "—";
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
        <Stack direction="row" alignItems="center" spacing={1}>
          <Typography variant="caption" color="text.secondary">turn {index + 1}</Typography>
          <Typography variant="subtitle2" sx={{ flexGrow: 1, ml: 1 }}>
            {shortDescription(group)}
          </Typography>
          {turn.reason && <Chip size="small" label={`→ ${turn.reason}`} />}
        </Stack>
        <Stack spacing={0.5} sx={{ mt: 1 }}>
          {group.parts.map((p, i) => {
            if (p.type === "reasoning") {
              return <Typography key={i} variant="body2" color="text.secondary">💭 {p.text}</Typography>;
            }
            if (p.type === "tool-call") {
              const matched = results.find((r) => r.toolCallID === p.toolCallID || r.callID === p.callID);
              return <ToolCallBlock key={i} call={p} result={matched} />;
            }
            if (p.type === "text") {
              return <Typography key={i} variant="body2">🗨 {p.text}</Typography>;
            }
            return null;
          })}
        </Stack>
        <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap">
          <Typography variant="caption" color="text.secondary">
            tools {calls.length} · reads {reads} · greps {greps} · edits {edits} ·{" "}
            tokens {formatTokens(turn.tokens_in)}/{formatTokens(turn.tokens_out)} ·{" "}
            cost ${turn.cost?.toFixed(4) ?? "—"} · {duration}
          </Typography>
        </Stack>
        <RawEventsToggle events={rawEvents} />
      </CardContent>
    </Card>
  );
}
