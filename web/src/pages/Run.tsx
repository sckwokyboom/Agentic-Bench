import { useEffect, useMemo } from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import { Stack, Box, Button, Typography } from "@mui/material";
import { useRunSession } from "../ws/useRunSession";
import ProgressHeader from "../components/ProgressHeader";
import RunSidebar from "../components/RunSidebar";
import EventStream from "../components/EventStream";
import { useCancelSession } from "../api/queries";
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
    let firstFinishedCond: string | null = null;
    let firstFinishedRep: number | null = null;
    let sessionFinished = false;
    const isolationOn = { nonce: true, shuffle: true };
    for (const e of ws.envelopes) {
      if (e.type === "session.started") {
        totalRuns = e.total_runs;
      } else if (e.type === "run.started") {
        runIdx = e.run_idx; condition = e.condition; rep = e.rep; running += 1;
      } else if (e.type === "run.finished") {
        running = Math.max(0, running - 1); done += 1;
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
      sessionFinished, firstFinishedCond, firstFinishedRep, isolationOn,
    };
  }, [ws.envelopes]);

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
      navigate(`/runs/${experimentName}/${derived.firstFinishedCond}/${derived.firstFinishedRep}`);
    }
  }, [derived.sessionFinished, derived.firstFinishedCond, derived.firstFinishedRep, experimentName, navigate]);

  return (
    <Stack spacing={2} sx={{ height: "100%" }}>
      <Stack direction="row" alignItems="center" spacing={2}>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>Live run · {sid}</Typography>
        <Button
          color="warning" variant="outlined"
          disabled={!sid || derived.sessionFinished || cancel.isPending}
          onClick={() => sid && cancel.mutateAsync(sid)}
        >Cancel</Button>
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
      />
      {derived.sessionFinished && experimentName === null && (
        <Typography color="warning.main">
          Session finished. Reopen via the Experiments list to view the trace.
        </Typography>
      )}
      <Stack direction="row" spacing={2} sx={{ flex: 1, minHeight: 0 }}>
        <Box sx={{ width: 280, overflow: "auto" }}>
          <RunSidebar conditions={conditionsArr} totalReps={totalReps} envelopes={ws.envelopes} />
        </Box>
        <Box sx={{ flex: 1, overflow: "hidden" }}>
          <EventStream envelopes={ws.envelopes} />
        </Box>
      </Stack>
    </Stack>
  );
}
