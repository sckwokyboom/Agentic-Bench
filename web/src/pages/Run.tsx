import { useEffect, useMemo } from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import { Stack, Box, Button, Typography, Chip } from "@mui/material";
import { useRunSession } from "../ws/useRunSession";
import ProgressHeader from "../components/ProgressHeader";
import RunSidebar from "../components/RunSidebar";
import EventStream from "../components/EventStream";
import { useCancelSession, useRuns } from "../api/queries";
import type { SessionStarted } from "../ws/envelope";

export default function Run() {
  const { sid } = useParams<{ sid: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const experimentName =
    (location.state as { experimentName?: string } | null)?.experimentName ?? null;
  const ws = useRunSession(sid);
  const cancel = useCancelSession();

  const derived = useMemo(() => {
    let totalRuns = 0, done = 0, running = 0;
    let runIdx = 0;
    let condition: string | null = null;
    let rep: number | null = null;
    let verifyPassed = 0, verifyFailed = 0, verifyTotal = 0;
    let serviceErrors = 0;
    let firstFinishedCond: string | null = null;
    let firstFinishedRep: number | null = null;
    let sessionFinished = false;
    // Real isolation flags from the live session.started envelope. The server
    // always sends `isolation`, but the field is optional-safe (replay/tests
    // may omit it) — fall back to on/on only when truly absent.
    let isolationOn = { nonce: true, shuffle: true };
    let batchId: string | null = null;
    let model: string | null = null;
    for (const e of ws.envelopes) {
      if (e.type === "session.started") {
        totalRuns = e.total_runs;
        if (e.isolation) {
          isolationOn = {
            nonce: e.isolation.nonce_prefix,
            shuffle: e.isolation.shuffle_order,
          };
        }
        if (e.batch_id !== undefined) batchId = e.batch_id;
        if (e.model !== undefined) model = e.model;
      } else if (e.type === "run.started") {
        runIdx = e.run_idx; condition = e.condition; rep = e.rep; running += 1;
      } else if (e.type === "run.finished") {
        running = Math.max(0, running - 1); done += 1;
        serviceErrors += e.n_service_errors ?? 0;
        if (e.verify?.status === "passed") {
          verifyPassed += e.verify.passed_count ?? 0;
          verifyTotal += (e.verify.passed_count ?? 0) + (e.verify.failed_count ?? 0);
        } else if (e.verify?.status === "failed") {
          verifyFailed += e.verify.failed_count ?? 0;
          verifyTotal += (e.verify.passed_count ?? 0) + (e.verify.failed_count ?? 0);
        }
        if (firstFinishedCond === null && e.finished) {
          firstFinishedCond = e.condition; firstFinishedRep = e.rep;
        }
      } else if (e.type === "session.finished") {
        sessionFinished = true;
      }
    }
    const pending = Math.max(0, totalRuns - done - running);
    return {
      totalRuns, done, running, pending, runIdx, condition, rep,
      verify: { passed: verifyPassed, failed: verifyFailed, total: verifyTotal },
      serviceErrors,
      sessionFinished, firstFinishedCond, firstFinishedRep, isolationOn, batchId, model,
    };
  }, [ws.envelopes]);

  const batchId = derived.batchId;

  // Resilience backstop: while the session is live, poll the batch's runs so a
  // `done` run becomes clickable even if a socket run.finished was missed.
  // Live envelopes still win for in-flight state (see RunSidebar merge).
  const polledRuns = useRuns(
    experimentName ?? undefined,
    batchId ?? undefined,
    { refetchInterval: derived.sessionFinished ? false : 2000 },
  );

  const conditionsArr = useMemo(() => {
    const e = ws.envelopes.find((x): x is SessionStarted => x.type === "session.started");
    return e ? e.conditions : [];
  }, [ws.envelopes]);

  const totalReps = derived.totalRuns && conditionsArr.length
    ? Math.max(1, Math.floor(derived.totalRuns / conditionsArr.length))
    : 0;

  useEffect(() => {
    if (
      derived.sessionFinished &&
      derived.firstFinishedCond !== null &&
      derived.firstFinishedRep !== null &&
      experimentName
    ) {
      const suffix = batchId ? `?batch=${encodeURIComponent(batchId)}` : "";
      navigate(`/runs/${experimentName}/${derived.firstFinishedCond}/${derived.firstFinishedRep}${suffix}`);
    }
  }, [derived.sessionFinished, derived.firstFinishedCond, derived.firstFinishedRep, experimentName, batchId, navigate]);

  return (
    <Stack spacing={2} sx={{ height: "100%" }}>
      <Stack direction="row" alignItems="center" spacing={1.5} flexWrap="wrap">
        <Typography variant="h5">
          Live run{experimentName ? ` · ${experimentName}` : ""}
        </Typography>
        {derived.model && (
          <Chip size="small" color="primary" variant="outlined" label={`model: ${derived.model}`} />
        )}
        <Typography variant="caption" color="text.secondary">{sid}</Typography>
        <Box sx={{ flexGrow: 1 }} />
        <Button
          color="warning" variant="outlined"
          disabled={!sid || derived.sessionFinished || cancel.isPending}
          onClick={() => sid && cancel.mutateAsync(sid)}
        >{cancel.isPending ? "Cancelling…" : derived.sessionFinished ? "Finished" : "Cancel"}</Button>
      </Stack>
      <ProgressHeader
        runIdx={derived.runIdx}
        totalRuns={derived.totalRuns}
        condition={derived.condition}
        rep={derived.rep}
        done={derived.done}
        running={derived.running}
        pending={derived.pending}
        verifyCounts={derived.verify}
        isolation={derived.isolationOn}
        serviceErrors={derived.serviceErrors}
      />
      {derived.sessionFinished && experimentName === null && (
        <Typography color="warning.main">
          Session finished. Reopen via the Experiments list to view the trace.
        </Typography>
      )}
      <Stack direction="row" spacing={2} sx={{ flex: 1, minHeight: 0 }}>
        <Box sx={{ width: 280, overflow: "auto" }}>
          <RunSidebar
            conditions={conditionsArr}
            totalReps={totalReps}
            envelopes={ws.envelopes}
            experimentName={experimentName}
            batchId={batchId}
            polledRuns={polledRuns.data}
          />
        </Box>
        <Box sx={{ flex: 1, overflow: "hidden" }}>
          <EventStream envelopes={ws.envelopes} />
        </Box>
      </Stack>
    </Stack>
  );
}
