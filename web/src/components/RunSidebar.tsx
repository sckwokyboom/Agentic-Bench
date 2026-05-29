import { Stack, Typography } from "@mui/material";
import RunSidebarCard from "./RunSidebarCard";
import type { Envelope } from "../ws/envelope";
import type { VerifyStatus } from "../api/types";

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
}

export default function RunSidebar({ conditions, totalReps, envelopes }: Props) {
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

  const groups: Record<string, Item[]> = {};
  for (const c of conditions) groups[c] = [];
  for (const it of map.values()) groups[it.condition]?.push(it);

  return (
    <Stack spacing={2}>
      {conditions.map((c) => (
        <Stack key={c} spacing={1}>
          <Typography variant="caption" color="text.secondary">{c}</Typography>
          {(groups[c] ?? [])
            .sort((a, b) => a.rep - b.rep)
            .map((it) => (
              <RunSidebarCard key={`${c}-${it.rep}`} {...it} />
            ))}
        </Stack>
      ))}
    </Stack>
  );
}
