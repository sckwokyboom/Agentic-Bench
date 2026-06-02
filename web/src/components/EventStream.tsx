import { useEffect, useMemo, useRef, useState } from "react";
import { Box, Stack, FormControlLabel, Checkbox, Typography } from "@mui/material";
import TurnCard from "./TurnCard";
import { turnsFromRawEvents, type UiTurn } from "../lib/traceModel";
import type { Envelope } from "../ws/envelope";

interface Props { envelopes: Envelope[]; }

export default function EventStream({ envelopes }: Props) {
  const [autoScroll, setAutoScroll] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  const rawEvents = useMemo(
    () =>
      envelopes
        .filter((e) => e.type === "raw_event")
        .map((e) => (e as Extract<Envelope, { type: "raw_event" }>).event),
    [envelopes],
  );

  const turns: UiTurn[] = useMemo(() => turnsFromRawEvents(rawEvents), [rawEvents]);

  const rawByMsg = (mid: string | null) =>
    rawEvents.filter((e: any) => e?.part?.messageID === mid);

  useEffect(() => {
    if (autoScroll) bottomRef.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [turns, autoScroll]);

  return (
    <Stack spacing={1} sx={{ height: "100%" }}>
      <Stack direction="row" alignItems="center">
        <FormControlLabel
          control={<Checkbox size="small" checked={autoScroll} onChange={() => setAutoScroll(!autoScroll)} />}
          label="auto-scroll"
        />
      </Stack>
      <Box sx={{ flex: 1, overflow: "auto", minHeight: 0 }}>
        <Stack spacing={2}>
          {turns.length === 0 && (
            <Typography variant="body2" color="text.secondary">No events yet.</Typography>
          )}
          {turns.map((t) => (
            <TurnCard
              key={t.messageId ?? t.index}
              turn={t}
              index={t.index}
              rawEvents={rawByMsg(t.messageId)}
            />
          ))}
        </Stack>
        <div ref={bottomRef} />
      </Box>
    </Stack>
  );
}
