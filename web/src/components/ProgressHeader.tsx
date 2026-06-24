import { Stack, Typography, LinearProgress, Box, Chip, Tooltip } from "@mui/material";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline";
import ScheduleIcon from "@mui/icons-material/Schedule";
import DataUsageIcon from "@mui/icons-material/DataUsage";
import { formatTokens } from "../lib/formatTokens";
import VerifyChip from "./VerifyChip";
import IsolationChip from "./IsolationChip";
import { formatEta, type ExperimentEstimate } from "../lib/eta";
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
  // Live aggregate of service/proxy errors summed across run.finished envelopes.
  serviceErrors?: number;
  // Time estimate for the experiment (shown as a prominent line below the bar).
  estimate?: ExperimentEstimate;
  // Cumulative token totals for the current run (Σ input billed / Σ generated)
  // plus peak = the largest single-request context (max tokensIn+tokensOut).
  tokens?: { inSum: number; outSum: number; peak: number } | null;
  // Model context window (max tokens); with peak → "% of context used".
  contextWindow?: number | null;
}

function pctColor(pct: number): "success" | "warning" | "error" {
  return pct < 70 ? "success" : pct < 90 ? "warning" : "error";
}

function EstimateLine({ estimate }: { estimate: ExperimentEstimate }) {
  if (estimate.state === "idle" || estimate.state === "done") return null;
  const text =
    estimate.state === "estimating" || estimate.totalSeconds == null || estimate.etaSeconds == null
      ? "Estimating run time…"
      : `≈ ${formatEta(estimate.totalSeconds)} total · ${formatEta(estimate.etaSeconds)} left · ${estimate.doneRuns}/${estimate.totalRuns} runs`;
  return (
    <Typography
      variant="body2"
      color="text.secondary"
      sx={{ display: "flex", alignItems: "center", gap: 0.5 }}
    >
      <ScheduleIcon fontSize="small" /> {text}
    </Typography>
  );
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
      {props.estimate && <EstimateLine estimate={props.estimate} />}
      {props.tokens && (props.tokens.inSum > 0 || props.tokens.outSum > 0) && (
        <Tooltip
          arrow
          title="Current run, cumulative. Σ in = total input tokens billed — the full context is re-sent every turn, so this grows fast. Σ out = total tokens generated."
        >
          <Typography
            variant="body2"
            color="text.secondary"
            sx={{ display: "flex", alignItems: "center", gap: 0.5, width: "fit-content", cursor: "help" }}
          >
            <DataUsageIcon fontSize="small" /> tokens · Σ in {formatTokens(props.tokens.inSum)} · Σ out {formatTokens(props.tokens.outSum)}
          </Typography>
        </Tooltip>
      )}
      {props.tokens && props.contextWindow && props.contextWindow > 0 && props.tokens.peak > 0 && (() => {
        const ctxPct = Math.min(100, (props.tokens!.peak / props.contextWindow!) * 100);
        return (
          <Tooltip
            arrow
            title="How full the model's context window got at its peak — the largest single request (input context + that turn's output) ÷ the window. This is occupancy, NOT the billed Σ in (which re-sends context every turn). Near 100% risks truncation/compaction."
          >
            <Box sx={{ width: "fit-content", minWidth: 240, cursor: "help" }}>
              <Typography variant="body2" color="text.secondary">
                context · {formatTokens(props.tokens.peak)} / {formatTokens(props.contextWindow)} ({ctxPct.toFixed(0)}% of window)
              </Typography>
              <LinearProgress variant="determinate" value={ctxPct} color={pctColor(ctxPct)} />
            </Box>
          </Tooltip>
        );
      })()}
      <Stack direction="row" spacing={1} flexWrap="wrap">
        <Chip size="small" label={`${props.done} done`} color="success" variant="outlined" />
        <Chip size="small" label={`${props.running} running`} color="info" variant="outlined" />
        <Chip size="small" label={`${props.pending} pending`} variant="outlined" />
        {(props.serviceErrors ?? 0) > 0 && (
          <Chip
            size="small"
            icon={<ErrorOutlineIcon />}
            label={`${props.serviceErrors} errors`}
            color="error"
          />
        )}
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
