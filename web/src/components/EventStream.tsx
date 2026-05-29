import { useEffect, useMemo, useRef, useState } from "react";
import { Box, Typography, Stack } from "@mui/material";
import EventFilterBar, { type EventFilters } from "./EventFilterBar";
import { groupEventsByTurn, type TurnGroup } from "../lib/groupEventsByTurn";
import type { Envelope } from "../ws/envelope";

interface Props { envelopes: Envelope[]; }

const defaultFilters: EventFilters = { reasoning: true, tool: true, text: true, error: true };

function matchesFilter(partType: string, f: EventFilters): boolean {
  if (partType === "reasoning" && !f.reasoning) return false;
  if ((partType === "tool-call" || partType === "tool-result") && !f.tool) return false;
  if (partType === "text" && !f.text) return false;
  if (partType === "error" && !f.error) return false;
  return true;
}

// The event pane is a fixed-dark terminal surface in BOTH app themes, so part
// colors are explicit bright values (GitHub-dark palette) that always read on
// the #0e1116 background — never MUI's *.dark / text.primary tokens, which
// resolve to dark-on-dark in light mode and were unreadable.
function partTone(partType: string): string {
  if (partType === "reasoning") return "#9aa7b8";       // muted grey-blue
  if (partType === "tool-call") return "#79b8ff";       // bright blue
  if (partType === "tool-result") return "#7ee787";     // bright green
  if (partType === "error") return "#ff7b72";           // bright red
  return "#e6edf3";                                      // llm text — near-white
}

export default function EventStream({ envelopes }: Props) {
  const [filters, setFilters] = useState<EventFilters>(defaultFilters);
  const [autoScroll, setAutoScroll] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  const groups: TurnGroup[] = useMemo(() => {
    const raw = envelopes
      .filter((e) => e.type === "raw_event")
      .map((e) => (e as Extract<Envelope, { type: "raw_event" }>).event);
    return groupEventsByTurn(raw);
  }, [envelopes]);

  useEffect(() => {
    if (autoScroll) bottomRef.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [groups, autoScroll]);

  return (
    <Stack spacing={1} sx={{ height: "100%" }}>
      <EventFilterBar
        value={filters} onChange={setFilters}
        autoScroll={autoScroll} onAutoScrollChange={setAutoScroll}
      />
      <Box sx={{
        flex: 1, overflow: "auto", fontFamily: "monospace", fontSize: 13,
        bgcolor: "#0e1116", color: "#dbe1ec", borderRadius: 1, p: 1.5,
        userSelect: "text",
      }}>
        {groups.map((g, i) => (
          <Box key={g.messageId} sx={{ mb: 2 }}>
            <Typography variant="caption" sx={{ color: "#8b98a9" }}>
              ━━ turn {i + 1} ━━ {g.reason && <>· {g.reason}</>}
            </Typography>
            {g.parts.filter((p) => matchesFilter(p.type, filters)).map((p, j) => (
              <Box key={j} sx={{ color: partTone(p.type), pl: 2, mt: 0.5 }}>
                {p.type === "reasoning" && <>💭 {p.text}</>}
                {p.type === "tool-call" && <>✎ {p.name} {JSON.stringify(p.input).slice(0, 200)}</>}
                {p.type === "tool-result" && <>✓ {p.name} → {String(p.output ?? "").slice(0, 200)}</>}
                {p.type === "text" && <>🗨 {p.text}</>}
                {p.type === "error" && <>⚠ {p.message ?? JSON.stringify(p).slice(0, 200)}</>}
              </Box>
            ))}
          </Box>
        ))}
        <div ref={bottomRef} />
      </Box>
    </Stack>
  );
}
