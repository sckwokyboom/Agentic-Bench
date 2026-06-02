import { Card, CardActionArea, CardContent, Stack, Typography } from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
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
  onOpen?: () => void;
}

const borderColor: Record<Props["state"], string> = {
  pending: "divider",
  running: "info.main",
  done: "success.main",
};

const stateIcon: Record<Props["state"], React.ReactNode> = {
  pending: null,
  running: <PlayArrowIcon fontSize="inherit" color="info" />,
  done: <CheckCircleIcon fontSize="inherit" color="success" />,
};

export default function RunSidebarCard(p: Props) {
  const clickable = p.state === "done" && Boolean(p.onOpen);

  const body = (
    <CardContent sx={{ py: 1.25 }}>
      <Stack spacing={0.5}>
        <Typography variant="body2"><b>{p.condition}</b> · rep {p.rep}</Typography>
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ display: "flex", alignItems: "center", gap: 0.5 }}
        >
          {stateIcon[p.state]}
          {p.state}
          {p.durationS != null && ` · ${p.durationS.toFixed(1)}s`}
        </Typography>
        <VerifyChip status={p.verifyStatus} passed={p.verifyPassed} failed={p.verifyFailed} />
        {clickable && (
          <Typography
            variant="caption"
            color="primary"
            sx={{ display: "flex", alignItems: "center", gap: 0.5 }}
          >
            <OpenInNewIcon fontSize="inherit" /> open trace
          </Typography>
        )}
      </Stack>
    </CardContent>
  );

  return (
    <Card variant="outlined" sx={{ borderLeft: 4, borderLeftColor: borderColor[p.state] }}>
      {clickable ? (
        <CardActionArea
          onClick={p.onOpen}
          aria-label={`open trace for ${p.condition} rep ${p.rep}`}
        >
          {body}
        </CardActionArea>
      ) : (
        body
      )}
    </Card>
  );
}
