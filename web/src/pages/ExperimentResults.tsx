import { useEffect, useState } from "react";
import { useNavigate, useParams, Link as RouterLink } from "react-router-dom";
import {
  Stack, Typography, CircularProgress, Alert, Button, Box, Link,
} from "@mui/material";
import { useQueryClient } from "@tanstack/react-query";
import {
  useRuns, useRunsSummary, useStartReverify, useReverifyStatus, qk,
} from "../api/queries";
import { ApiError } from "../api/client";
import SummaryTable from "../components/SummaryTable";
import RunsTable from "../components/RunsTable";

export default function ExperimentResults() {
  const { name } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const runs = useRuns(name);
  const summary = useRunsSummary(name);

  const qc = useQueryClient();
  const start = useStartReverify();
  const [verifyId, setVerifyId] = useState<string | null>(null);
  const job = useReverifyStatus(verifyId);
  // `verifyId !== null` keeps the button disabled between the POST resolving and
  // the first poll, so a fast double-click can't start a second job.
  const running = start.isPending || verifyId !== null || job.data?.state === "running";

  useEffect(() => {
    if (job.data?.state === "done" || job.data?.state === "error") {
      if (name) {
        qc.invalidateQueries({ queryKey: qk.runs(name) });
        qc.invalidateQueries({ queryKey: qk.runsSummary(name) });
      }
      setVerifyId(null);
    }
  }, [job.data?.state, qc, name]);

  async function handleReverifyAll() {
    if (!name) return;
    const { verify_id } = await start.mutateAsync({ name });
    setVerifyId(verify_id);
  }

  return (
    <Stack spacing={3} sx={{ maxWidth: 1100, mx: "auto" }}>
      <Stack direction="row" alignItems="center" spacing={2}>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>Results · {name}</Typography>
        <Button variant="outlined" size="small" onClick={handleReverifyAll} disabled={running}>
          {running
            ? `Re-verifying ${job.data?.done ?? 0}/${job.data?.total ?? "…"}`
            : "Re-verify all"}
        </Button>
        <Button component={RouterLink} to={`/experiments/${name}`} variant="outlined" size="small">
          Edit
        </Button>
      </Stack>

      <Box>
        <Typography variant="subtitle2" gutterBottom>Aggregate (baseline vs augmented)</Typography>
        {summary.isLoading && <CircularProgress size={20} />}
        {summary.error && (
          (summary.error as ApiError)?.status === 404
            ? <Typography variant="body2" color="text.secondary">No runs yet — nothing to aggregate.</Typography>
            : <Alert severity="error">Failed to load summary.</Alert>
        )}
        {summary.data && <SummaryTable summary={summary.data} />}
      </Box>

      <Box>
        <Typography variant="subtitle2" gutterBottom>Runs</Typography>
        {runs.isLoading && <CircularProgress size={20} />}
        {runs.error && <Alert severity="error">Failed to load runs.</Alert>}
        {runs.data && (
          <RunsTable
            rows={runs.data}
            onOpen={(condition, rep) => navigate(`/runs/${name}/${condition}/${rep}`)}
          />
        )}
      </Box>

      <Link component={RouterLink} to="/runs" variant="body2">← all experiments with runs</Link>
    </Stack>
  );
}
