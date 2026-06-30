import { type ReactNode } from "react";
import { useNavigate, useParams, useSearchParams, Link as RouterLink } from "react-router-dom";
import { Stack, Typography, CircularProgress, Alert, Box, Chip, Tooltip, LinearProgress, Link } from "@mui/material";
import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import { useTrace, useEvents, useRuns, useMetrics } from "../api/queries";
import {
  turnsFromTrace, observationTokensByTool, observationTokensTotal, realInputTokensTotal,
  peakContextTokens,
} from "../lib/traceModel";
import { formatTokens } from "../lib/formatTokens";
import VerdictBanner from "../components/VerdictBanner";
import ValiditySignals from "../components/ValiditySignals";
import AggregateStatsBar from "../components/AggregateStatsBar";
import TurnCard from "../components/TurnCard";
import VerifyCard from "../components/VerifyCard";
import FinalDiffCard from "../components/FinalDiffCard";
import RunLogToggle from "../components/RunLogToggle";
import MethodComparisonCard from "../components/MethodComparisonCard";
import MetricsDrawer from "../components/MetricsDrawer";
import TraceRunSwitcher from "../components/TraceRunSwitcher";
import SafeTraceButton from "../components/SafeTraceButton";
import PhaseDivider from "../components/PhaseDivider";

function outcomeColor(o: string): "success" | "warning" | "error" | "default" {
  if (o === "green") return "success";
  if (o === "compile-fail") return "error";
  if (o === "stuck" || o === "budget") return "warning";
  return "default";
}

export default function TraceView() {
  const { name, condition, rep } = useParams<{ name: string; condition: string; rep: string }>();
  const navigate = useNavigate();
  const [sp] = useSearchParams();
  // Batch is a search param, not a path segment; undefined → server's newest.
  const batch = sp.get("batch") ?? undefined;
  const batchQs = batch ? `?batch=${encodeURIComponent(batch)}` : "";
  const repN = Number(rep);
  const trace = useTrace(name!, condition!, repN, batch);
  const events = useEvents(name!, condition!, repN, batch);
  const metrics = useMetrics(name!, condition!, repN, batch);
  const runs = useRuns(name, batch);

  // Back to the comparison/metrics page for THIS experiment + batch (the batch
  // is preserved, and the exclusion choice is restored there from localStorage).
  const backToResults = (
    <Link
      component={RouterLink}
      to={`/runs/${name}${batchQs}`}
      variant="body2"
      sx={{ display: "inline-flex", alignItems: "center", gap: 0.5, alignSelf: "flex-start" }}
    >
      <ArrowBackIcon fontSize="inherit" /> Back to results · {name}
    </Link>
  );

  if (trace.isLoading) {
    return <Stack spacing={2}>{backToResults}<CircularProgress /></Stack>;
  }
  if (trace.error || !trace.data) {
    return (
      <Stack spacing={2}>
        {backToResults}
        <Alert severity="error">Failed to load trace.</Alert>
      </Stack>
    );
  }

  const uiTurns = turnsFromTrace(trace.data);
  const rawByMsg = (mid: string | null) =>
    (events.data ?? []).filter((e: any) => e?.part?.messageID === mid);

  // How much context the agent's tool outputs poured in (estimate), and the real
  // provider input total for contrast (the gap ≈ what OpenCode compacted away).
  const obsByTool = observationTokensByTool(uiTurns);
  const obsTotal = observationTokensTotal(uiTurns);
  const realIn = realInputTokensTotal(uiTurns);
  const obsStr = Object.entries(obsByTool)
    .sort((a, b) => b[1] - a[1])
    .map(([n, v]) => `${n} ≈${formatTokens(v)}`)
    .join(" · ");

  // Validity signals: metrics is the authoritative source for counts/flags;
  // trace carries the human-readable service-error messages. `made_source_changes`
  // lives only on metrics — fall back to the trace's diff summary otherwise.
  const m = metrics.data;
  const nServiceErrors = m?.n_service_errors ?? trace.data.n_service_errors ?? 0;
  const verifyInsensitive = m?.verify_insensitive ?? trace.data.verify_insensitive ?? false;
  const interruptedReason = m?.interrupted_reason ?? null;
  const madeSourceChanges = m?.made_source_changes
    ?? ((trace.data.final_diff_summary?.files?.length ?? 0) > 0);

  // Context-window occupancy: peak single-request (in+out) ÷ the model's window.
  const ctxWindow = trace.data.model_context_window ?? null;
  const ctxPeak = peakContextTokens(uiTurns);
  const ctxPct = ctxWindow && ctxWindow > 0 ? Math.min(100, (ctxPeak / ctxWindow) * 100) : null;

  return (
    <Stack direction="row" spacing={3} sx={{ maxWidth: 1280, mx: "auto", alignItems: "flex-start" }}>
      <Box sx={{ position: "sticky", top: 0, alignSelf: "flex-start", flexShrink: 0 }}>
        {runs.data && (
          <TraceRunSwitcher
            rows={runs.data}
            current={{ condition: condition!, rep: repN }}
            onSelect={(c, r) => navigate(`/runs/${name}/${c}/${r}${batchQs}`)}
          />
        )}
      </Box>

      <Stack spacing={2} sx={{ flex: 1, minWidth: 0 }}>
        {backToResults}
        <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between">
          <Typography variant="h5">{name} / {condition} / rep {repN}</Typography>
          <SafeTraceButton name={name!} condition={condition!} rep={repN} batch={batch} />
        </Stack>
        <ValiditySignals
          nServiceErrors={nServiceErrors}
          interruptedReason={interruptedReason}
          serviceErrorMessages={trace.data.service_error_messages}
          verifyInsensitive={verifyInsensitive}
          cheating={m?.cheating}
        />
        <VerdictBanner trace={trace.data} />
        {trace.data.verify_baseline_unknown && (
          <Alert severity="warning">
            The reference project itself does not pass verify (build/environment issue) —
            run verdicts may be unreliable.
          </Alert>
        )}
        {metrics.data && <AggregateStatsBar metrics={metrics.data} />}
        {trace.data.orchestration_outcome && (
          <Stack spacing={0.5}>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
              <Chip size="small" color={outcomeColor(trace.data.orchestration_outcome)}
                icon={<SettingsOutlinedIcon />} label={`orchestration: ${trace.data.orchestration_outcome}`} />
              <Typography variant="caption" color="text.secondary">
                {trace.data.controller_test_runs ?? 0} suite runs · {trace.data.accepted_rounds ?? 0} accepted · {trace.data.reverted_rounds ?? 0} reverted
              </Typography>
            </Stack>
            <Typography variant="caption" color="text.secondary">
              <b>Phased orchestration</b>: our controller (deterministic code, not the model) drives the
              agent through fixed phases. Each phase it sends a prompt it composed + scoped tools; the
              agent (model) does the work — the <b>contract / plan / code edits are the agent's output</b>.
              After each phase the controller gates that output and runs the test suite, accepting or
              reverting. Below: the <b>phase bands</b> + <b>“controller” cards</b> are the controller;
              <b> “turn N” cards</b> are the agent.
            </Typography>
          </Stack>
        )}
        {obsTotal > 0 && (
          <Typography variant="caption" color="text.secondary">
            Context from tool outputs: ≈{formatTokens(obsTotal)} tok ({obsStr}) · real Σ input {formatTokens(realIn)}
          </Typography>
        )}
        {ctxPct !== null && ctxPeak > 0 && (
          <Tooltip
            arrow
            title="How full the model's context window got at its peak — the largest single request (input context + that turn's output) ÷ the window. Occupancy, NOT the billed Σ input (context is re-sent each turn). Near 100% risks truncation/compaction."
          >
            <Box sx={{ width: "fit-content", minWidth: 260, cursor: "help" }}>
              <Typography variant="caption" color="text.secondary">
                Context window: peak {formatTokens(ctxPeak)} / {formatTokens(ctxWindow!)} ({ctxPct.toFixed(0)}% used)
              </Typography>
              <LinearProgress variant="determinate" value={ctxPct}
                color={ctxPct < 70 ? "success" : ctxPct < 90 ? "warning" : "error"} />
            </Box>
          </Tooltip>
        )}
        {(() => {
          // Insert a phase divider when the phase changes (phased traces only;
          // baseline turns have phase === null → no dividers, unchanged render).
          let prevPhase: string | null = null;
          const out: ReactNode[] = [];
          for (const t of uiTurns) {
            if (t.phase && t.phase !== prevPhase) {
              out.push(<PhaseDivider key={`phase-${t.index}`} phase={t.phase} />);
              prevPhase = t.phase;
            }
            out.push(
              <TurnCard key={t.messageId ?? t.index} turn={t} index={t.index} rawEvents={rawByMsg(t.messageId)} />,
            );
          }
          return out;
        })()}
        <VerifyCard trace={trace.data} name={name!} condition={condition!} rep={repN} batch={batch} />
        <FinalDiffCard
          name={name!} condition={condition!} rep={repN} batch={batch}
          madeSourceChanges={madeSourceChanges}
        />
        <MethodComparisonCard name={name!} condition={condition!} rep={repN} batch={batch} />
        <RunLogToggle name={name!} condition={condition!} rep={repN} batch={batch} />
        <MetricsDrawer name={name!} condition={condition!} rep={repN} batch={batch} />
      </Stack>
    </Stack>
  );
}
