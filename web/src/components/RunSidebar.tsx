import { Stack, Typography } from "@mui/material";
import { useNavigate } from "react-router-dom";
import RunSidebarCard from "./RunSidebarCard";
import type { Envelope } from "../ws/envelope";
import type { RunSummary, VerifyStatus } from "../api/types";

interface Item {
  condition: string;
  rep: number;
  state: "pending" | "running" | "done";
  verifyStatus: VerifyStatus | "running" | null;
  verifyPassed: number | null;
  verifyFailed: number | null;
}

interface Props {
  conditions: string[];
  totalReps: number;
  envelopes: Envelope[];
  experimentName?: string | null;
  batchId?: string | null;
  // Optional resilience backstop: polled runs confirm a run is `done` (and its
  // verify status) even if a socket event was missed. Live envelopes win for
  // in-flight state; polled rows only ever upgrade a card to `done`.
  polledRuns?: RunSummary[];
}

export default function RunSidebar({
  conditions,
  totalReps,
  envelopes,
  experimentName,
  batchId,
  polledRuns,
}: Props) {
  const navigate = useNavigate();

  const map = new Map<string, Item>();
  for (const c of conditions) {
    for (let r = 0; r < totalReps; r += 1) {
      map.set(`${c}/${r}`, {
        condition: c, rep: r, state: "pending",
        verifyStatus: null, verifyPassed: null, verifyFailed: null,
      });
    }
  }
  for (const e of envelopes) {
    if (e.type === "run.started") {
      const it = map.get(`${e.condition}/${e.rep}`);
      if (it) it.state = "running";
    } else if (e.type === "run.finished") {
      const it = map.get(`${e.condition}/${e.rep}`);
      if (it) {
        it.state = "done";
        it.verifyStatus = e.verify.status as VerifyStatus | null;
        it.verifyPassed = e.verify.passed_count;
        it.verifyFailed = e.verify.failed_count;
      }
    }
  }

  // Backstop: a polled run row confirms a card is `done` if the live stream
  // never delivered its run.finished envelope. Never downgrades a card.
  for (const r of polledRuns ?? []) {
    const it = map.get(`${r.condition}/${r.rep}`);
    if (it && it.state !== "done" && r.finished) {
      it.state = "done";
      it.verifyStatus = r.verify_status;
    }
  }

  const groups: Record<string, Item[]> = {};
  for (const c of conditions) groups[c] = [];
  for (const it of map.values()) groups[it.condition]?.push(it);

  const canOpen = (it: Item) =>
    it.state === "done" && Boolean(experimentName) && Boolean(batchId);

  const open = (it: Item) => {
    if (!experimentName || !batchId) return;
    navigate(
      `/runs/${experimentName}/${it.condition}/${it.rep}` +
        `?batch=${encodeURIComponent(batchId)}`,
    );
  };

  return (
    <Stack spacing={2}>
      {conditions.map((c) => (
        <Stack key={c} spacing={1}>
          <Typography variant="caption" color="text.secondary">{c}</Typography>
          {(groups[c] ?? [])
            .sort((a, b) => a.rep - b.rep)
            .map((it) => (
              <RunSidebarCard
                key={`${c}-${it.rep}`}
                {...it}
                onOpen={canOpen(it) ? () => open(it) : undefined}
              />
            ))}
        </Stack>
      ))}
    </Stack>
  );
}
