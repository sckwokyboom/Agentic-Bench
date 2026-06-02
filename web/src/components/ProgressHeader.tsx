import { Stack, Typography, LinearProgress, Box, Chip } from "@mui/material";
import VerifyChip from "./VerifyChip";
import IsolationChip from "./IsolationChip";
import type { VerifyStatus } from "../api/types";

interface Props {
  runIdx: number;       // 1-based
  totalRuns: number;
  condition: string | null;
  rep: number | null;
  done: number;
  running: number;
  pending: number;
  verifyCounts: { passed: number; failed: number; total: number };
  currentCommand?: string | null;
  isolation: { nonce: boolean; shuffle: boolean };
  baselineStatus?: VerifyStatus | null;
}

export default function ProgressHeader(props: Props) {
  const pct = props.totalRuns === 0 ? 0 : (props.done / props.totalRuns) * 100;
  // Derive the aggregate verify status from real counts instead of hardcoding:
  // failed if any failed, passed if any results and none failed, otherwise
  // neutral (null) so VerifyChip renders "no tests" rather than a green 0/0.
  const { passed: vPassed, failed: vFailed, total: vTotal } = props.verifyCounts;
  const verifyStatus: VerifyStatus | null =
    vFailed > 0 ? "failed" : vTotal > 0 ? "passed" : null;
  return (
    <Stack spacing={1}>
      <Typography variant="h6">
        Run {props.runIdx}/{props.totalRuns}
        {props.condition && <> · condition: <b>{props.condition}</b></>}
        {props.rep !== null && <> · rep: <b>{props.rep}</b></>}
      </Typography>
      <LinearProgress variant="determinate" value={pct} />
      <Stack direction="row" spacing={1} flexWrap="wrap">
        <Chip size="small" label={`${props.done} done`} color="success" variant="outlined" />
        <Chip size="small" label={`${props.running} running`} color="info" variant="outlined" />
        <Chip size="small" label={`${props.pending} pending`} variant="outlined" />
        <Box sx={{ flex: 1 }} />
        <VerifyChip
          status={verifyStatus}
          passed={vPassed}
          failed={vFailed}
        />
        {props.baselineStatus && (
          <Chip
            size="small"
            label={`baseline ${props.baselineStatus}`}
            color={props.baselineStatus === "passed" ? "success" : "warning"}
            variant="outlined"
          />
        )}
        <IsolationChip nonce={props.isolation.nonce} shuffle={props.isolation.shuffle} />
        {props.currentCommand && (
          <Chip size="small" label={`cmd: ${props.currentCommand}`} variant="outlined" />
        )}
      </Stack>
    </Stack>
  );
}
