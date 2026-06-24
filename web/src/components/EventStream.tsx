import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Box, Stack, FormControlLabel, Checkbox, Typography } from "@mui/material";
import TurnCard from "./TurnCard";
import PhaseDivider from "./PhaseDivider";
import { turnsFromRawEvents } from "../lib/traceModel";
import type { Envelope } from "../ws/envelope";

interface Props { envelopes: Envelope[]; }

export default function EventStream({ envelopes }: Props) {
  const [autoScroll, setAutoScroll] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Scope to the CURRENT run only (the highest run_idx seen) so a multi-run
  // session doesn't mix several traces into one stream and the per-turn counter
  // stays honest for the run on screen. Phased runs share one run_idx across all
  // their phases (see _PerRunPublishingClient), so a phased run stays whole.
  const { rawEvents, runLabel } = useMemo(() => {
    const raws = envelopes.filter(
      (e): e is Extract<Envelope, { type: "raw_event" }> => e.type === "raw_event",
    );
    if (raws.length === 0)
      return { rawEvents: [] as Record<string, unknown>[], runLabel: null as string | null };
    const curIdx = raws.reduce((m, e) => Math.max(m, e.run_idx), 0);
    const cur = raws.filter((e) => e.run_idx === curIdx);
    const last = cur[cur.length - 1];
    return {
      rawEvents: cur.map((e) => e.event),
      runLabel: last ? `run ${curIdx} · ${last.condition} · rep ${last.rep}` : null,
    };
  }, [envelopes]);

  const { turns, rawByMsg } = useMemo(() => {
    const built = turnsFromRawEvents(rawEvents);
    // Single pass: group raw events by their part's messageID.
    const grouped = new Map<string, unknown[]>();
    for (const e of rawEvents) {
      const mid = (e as { part?: { messageID?: string } })?.part?.messageID;
      if (mid == null) continue;
      const bucket = grouped.get(mid);
      if (bucket) bucket.push(e);
      else grouped.set(mid, [e]);
    }
    return { turns: built, rawByMsg: grouped };
  }, [rawEvents]);

  const rawFor = (mid: string | null): unknown[] =>
    mid != null ? rawByMsg.get(mid) ?? [] : [];

  useEffect(() => {
    if (autoScroll) bottomRef.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [turns, autoScroll]);

  return (
    <Stack spacing={1} sx={{ height: "100%" }}>
      <Stack direction="row" alignItems="center" spacing={1}>
        <FormControlLabel
          control={<Checkbox size="small" checked={autoScroll} onChange={() => setAutoScroll(!autoScroll)} />}
          label="auto-scroll"
        />
        {runLabel && (
          <Typography variant="caption" color="text.secondary">showing {runLabel}</Typography>
        )}
      </Stack>
      <Box sx={{ flex: 1, overflow: "auto", minHeight: 0 }}>
        <Stack spacing={2}>
          {turns.length === 0 && (
            <Typography variant="body2" color="text.secondary">No events yet.</Typography>
          )}
          {(() => {
            // Insert a phase divider when the orchestration phase changes, so
            // the live stream shows the controller's hand-offs (understand →
            // implement → diagnose …). Plain agent runs have phase === null →
            // no dividers, unchanged render.
            let prevPhase: string | null = null;
            const out: ReactNode[] = [];
            for (const t of turns) {
              if (t.phase && t.phase !== prevPhase) {
                out.push(<PhaseDivider key={`phase-${t.index}`} phase={t.phase} />);
                prevPhase = t.phase;
              }
              out.push(
                <TurnCard
                  key={t.messageId ?? `t-${t.index}`}
                  turn={t}
                  index={t.index}
                  rawEvents={rawFor(t.messageId)}
                />,
              );
            }
            return out;
          })()}
        </Stack>
        <div ref={bottomRef} />
      </Box>
    </Stack>
  );
}
