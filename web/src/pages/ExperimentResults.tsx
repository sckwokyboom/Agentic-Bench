import { useEffect, useState } from "react";
import { useNavigate, useParams, Link as RouterLink } from "react-router-dom";
import {
  Stack, Typography, CircularProgress, Alert, Button, Box, Link,
  FormControl, InputLabel, Select, MenuItem,
} from "@mui/material";
import type { SelectChangeEvent } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import { useQueryClient } from "@tanstack/react-query";
import {
  useRuns, useRunsSummary, useBatches, useStartReverify, useReverifyStatus,
} from "../api/queries";
import { ApiError } from "../api/client";
import type { RunBatch } from "../api/types";
import SummaryTable from "../components/SummaryTable";
import RunsTable from "../components/RunsTable";

// Batch ids are "YYYYMMDD-HHMMSS" UTC timestamps (or the literal "legacy").
// Format lightly for display but keep the raw id as the option value.
function formatBatchLabel(id: string): string {
  const m = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})$/.exec(id);
  if (!m) return id;
  const [, y, mo, d, h, mi, s] = m;
  return `${y}-${mo}-${d} ${h}:${mi}:${s} UTC`;
}

export default function ExperimentResults() {
  const { name } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const batches = useBatches(name);

  // Default to the newest batch (server returns newest-first → index 0).
  const [batch, setBatch] = useState<string | undefined>(undefined);
  const batchList: RunBatch[] = batches.data ?? [];
  useEffect(() => {
    // Seed/repair the selection once batches arrive (or when name changes).
    if (batchList.length === 0) return;
    const stillValid = batch != null && batchList.some((b) => b.id === batch);
    if (!stillValid) setBatch(batchList[0]?.id);
  }, [batchList, batch]);

  const runs = useRuns(name, batch);
  const summary = useRunsSummary(name, batch);

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
        // Bare prefixes invalidate every batch variant of these queries.
        qc.invalidateQueries({ queryKey: ["runs", name] });
        qc.invalidateQueries({ queryKey: ["runsSummary", name] });
      }
      setVerifyId(null);
    }
  }, [job.data?.state, qc, name]);

  async function handleReverifyAll() {
    if (!name) return;
    // Re-verify the currently-selected batch (undefined → newest, server-side).
    const { verify_id } = await start.mutateAsync({ name, batch });
    setVerifyId(verify_id);
  }

  function handleBatchChange(e: SelectChangeEvent) {
    setBatch(e.target.value);
  }

  // Thread the selected batch through to TraceView via ?batch=.
  const batchQs = batch ? `?batch=${encodeURIComponent(batch)}` : "";
  const showSelector = batchList.length > 0;

  return (
    <Stack spacing={3} sx={{ maxWidth: 1100, mx: "auto" }}>
      <Stack direction="row" alignItems="center" spacing={2}>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>Results · {name}</Typography>
        {showSelector && (
          <FormControl size="small" sx={{ minWidth: 220 }}>
            <InputLabel id="batch-select-label">Batch</InputLabel>
            <Select
              labelId="batch-select-label"
              label="Batch"
              value={batch ?? ""}
              onChange={handleBatchChange}
              disabled={batchList.length <= 1}
            >
              {batchList.map((b) => (
                <MenuItem key={b.id} value={b.id}>
                  {formatBatchLabel(b.id)} · {b.valid_runs}/{b.total_runs}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        )}
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
            onOpen={(condition, rep) => navigate(`/runs/${name}/${condition}/${rep}${batchQs}`)}
          />
        )}
      </Box>

      <Link component={RouterLink} to="/runs" variant="body2"
        sx={{ display: "inline-flex", alignItems: "center", gap: 0.5 }}>
        <ArrowBackIcon fontSize="inherit" /> all experiments with runs
      </Link>
    </Stack>
  );
}
