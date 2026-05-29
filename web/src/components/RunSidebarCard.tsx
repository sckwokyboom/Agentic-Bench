import { Card, CardContent, Stack, Typography } from "@mui/material";
import VerifyChip from "./VerifyChip";
import type { VerifyStatus } from "../api/types";

interface Props {
  condition: string;
  rep: number;
  state: "pending" | "running" | "done";
  verifyStatus: VerifyStatus | "running" | null;
  verifyPassed: number | null;
  verifyFailed: number | null;
  durationS?: number | null;
}

const borderColor: Record<Props["state"], string> = {
  pending: "divider",
  running: "info.main",
  done: "success.main",
};

export default function RunSidebarCard(p: Props) {
  return (
    <Card variant="outlined" sx={{ borderLeft: 4, borderLeftColor: borderColor[p.state] }}>
      <CardContent sx={{ py: 1.25 }}>
        <Stack spacing={0.5}>
          <Typography variant="body2"><b>{p.condition}</b> · rep {p.rep}</Typography>
          <Typography variant="caption" color="text.secondary">
            {p.state} {p.durationS != null && `· ${p.durationS.toFixed(1)}s`}
          </Typography>
          <VerifyChip status={p.verifyStatus} passed={p.verifyPassed} failed={p.verifyFailed} />
        </Stack>
      </CardContent>
    </Card>
  );
}
