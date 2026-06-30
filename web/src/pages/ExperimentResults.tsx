import { useEffect, useState } from "react";
import { useNavigate, useParams, Link as RouterLink } from "react-router-dom";
import {
  Stack, Typography, CircularProgress, Alert, Button, Box, Link,
  FormControl, InputLabel, Select, MenuItem,
} from "@mui/material";
import type { SelectChangeEvent } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import ReplayIcon from "@mui/icons-material/Replay";
import CalculateIcon from "@mui/icons-material/Calculate";
import EditIcon from "@mui/icons-material/Edit";
import { useQueryClient } from "@tanstack/react-query";
import {
  useRuns, useRunsSummary, useBatches, useStartReverify, useReverifyStatus,
  useRecomputeMetrics, usePanel,
} from "../api/queries";
import { ApiError } from "../api/client";
import type { Aggregate, RunBatch } from "../api/types";
import SummaryTable from "../components/SummaryTable";
import RunsTable from "../components/RunsTable";
import ResultsExportButton from "../components/ResultsExportButton";
import SafeTraceButton from "../components/SafeTraceButton";
import ValiditySignals from "../components/ValiditySignals";

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

  // Screening comparison panel: median|mean aggregate + a per-run include/exclude
  // set (keyed "condition/rep"). Both feed usePanel so the server recomputes every
  // aggregate. The exclusion choice is remembered per (experiment, batch) in
  // localStorage, so a reload restores it; switching batch loads that batch's set.
  const [agg, setAgg] = useState<Aggregate>("median");
  const exclKey = name && batch ? `ab:excluded:${name}:${batch}` : null;
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  useEffect(() => {
    if (!exclKey) { setExcluded(new Set()); return; }
    try {
      const raw = localStorage.getItem(exclKey);
      setExcluded(new Set(raw ? (JSON.parse(raw) as string[]) : []));
    } catch {
      setExcluded(new Set());
    }
  }, [exclKey]);
  const panel = usePanel(name, batch, "baseline", agg, [...excluded]);
  const toggleRun = (key: string) =>
    setExcluded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      if (exclKey) {
        try { localStorage.setItem(exclKey, JSON.stringify([...next])); } catch { /* quota/private mode */ }
      }
      return next;
    });

  const qc = useQueryClient();
  const start = useStartReverify();
  const recompute = useRecomputeMetrics();
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
        // Verdicts changed → drop the memoised comparison panels too.
        qc.invalidateQueries({ queryKey: ["panel", name] });
      }
      setVerifyId(null);
    }
  }, [job.data?.state, qc, name]);

  // While a re-verify job is in flight, drive per-row progress in the table:
  // which run is being verified now (current), and the fresh verdicts of the
  // ones already done (so each row updates live, not just at the end).
  const reverifyProgress = running && job.data
    ? {
        current: job.data.current,
        resultByKey: Object.fromEntries(
          (job.data.results ?? []).map((r) => [`${r.condition}/${r.rep}`, r.status]),
        ),
      }
    : undefined;

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

  // Insensitive verify is a property of the task, so a single flagged run taints
  // the whole batch's pass/fail counts — surface the banner if any row is set.
  const anyInsensitive = (runs.data ?? []).some((r) => r.verify_insensitive);

  return (
    <Stack spacing={3} sx={{ maxWidth: 1100, mx: "auto" }}>
      <Stack direction="row" alignItems="center" spacing={2} sx={{ flexWrap: "wrap", rowGap: 1 }}>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>Results · {name}</Typography>
        {showSelector && (
          <FormControl size="small" sx={{ minWidth: 240 }}>
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
      </Stack>

      {/* Actions get their own full-width, wrapping row so they're never squeezed;
          every action is small+outlined with an icon and a shared min-width. */}
      <Stack direction="row" spacing={1.5} sx={{ flexWrap: "wrap", gap: 1.5 }}>
        <Button
          variant="outlined" size="small" startIcon={<ReplayIcon />} sx={{ minWidth: 150 }}
          onClick={handleReverifyAll} disabled={running}
        >
          {running
            ? `Re-verifying ${job.data?.done ?? 0}/${job.data?.total ?? "…"}`
            : "Re-verify all"}
        </Button>
        <Button
          variant="outlined" size="small" startIcon={<CalculateIcon />} sx={{ minWidth: 150 }}
          disabled={recompute.isPending || !name}
          onClick={() => name && recompute.mutate({ name, batch })}
          title="Recompute metrics (tests executed, tokens…) from saved traces — no agent re-run"
        >
          {recompute.isPending ? "Recomputing…" : "Recompute metrics"}
        </Button>
        <Button
          component={RouterLink} to={`/experiments/${name}`}
          variant="outlined" size="small" startIcon={<EditIcon />} sx={{ minWidth: 150 }}
        >
          Edit
        </Button>
        <ResultsExportButton
          experimentName={name ?? ""}
          batchLabel={batch ? formatBatchLabel(batch) : null}
          summary={summary.data}
          runs={runs.data}
        />
        <SafeTraceButton name={name ?? ""} batch={batch} label="Safe traces" />
      </Stack>

      {anyInsensitive && <ValiditySignals verifyInsensitive />}

      <Box>
        <Typography variant="subtitle2" gutterBottom>Comparison vs baseline</Typography>
        {panel.isLoading && <CircularProgress size={20} />}
        {panel.error && (
          (panel.error as ApiError)?.status === 404
            ? <Typography variant="body2" color="text.secondary">No runs yet — nothing to compare.</Typography>
            : <Alert severity="error">Failed to load comparison.</Alert>
        )}
        {panel.data && (
          <SummaryTable
            panel={panel.data}
            agg={agg}
            onAggChange={setAgg}
            busy={panel.isFetching && !panel.isLoading}
          />
        )}
      </Box>

      <Box>
        <Typography variant="subtitle2" gutterBottom>Runs</Typography>
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
          Tick/untick to include a run in the comparison above; click a row to open its trace.
        </Typography>
        {runs.isLoading && <CircularProgress size={20} />}
        {runs.error && <Alert severity="error">Failed to load runs.</Alert>}
        {runs.data && (
          <RunsTable
            rows={runs.data}
            reverify={reverifyProgress}
            excluded={excluded}
            onToggleRun={toggleRun}
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
