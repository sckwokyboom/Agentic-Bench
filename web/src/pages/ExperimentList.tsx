import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Stack, Box, Typography, Button, Table, TableHead, TableBody, TableRow,
  TableCell, IconButton, CircularProgress, Alert, Link, Checkbox, Chip,
  LinearProgress,
} from "@mui/material";
import DeleteIcon from "@mui/icons-material/DeleteOutline";
import EditIcon from "@mui/icons-material/EditOutlined";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import AssessmentIcon from "@mui/icons-material/Assessment";
import { Link as RouterLink } from "react-router-dom";
import StatusPill, { type ExperimentStatus } from "../components/StatusPill";
import UploadYamlButton from "../components/UploadYamlButton";
import NewExperimentDialog from "../components/NewExperimentDialog";
import DeleteExperimentDialog from "../components/DeleteExperimentDialog";
import {
  useExperiments, useDeleteExperiment, useStartRun, useSaveExperiment,
  useCostSummary, useQueue, useStartQueue, useCancelQueue,
} from "../api/queries";
import type { ExperimentSummary } from "../api/types";

function statusOf(e: ExperimentSummary): ExperimentStatus {
  if (!e.has_fixture) return "no_fixture";
  return "ready";
}

export default function ExperimentList() {
  const navigate = useNavigate();
  const list = useExperiments();
  const del = useDeleteExperiment();
  const start = useStartRun();
  const cost = useCostSummary();
  const save = useSaveExperiment();
  const [toDelete, setToDelete] = useState<string | null>(null);
  const [newOpen, setNewOpen] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const queue = useQueue();
  const startQueue = useStartQueue();
  const cancelQueue = useCancelQueue();
  const queueRunning = queue.data?.running ?? false;

  function toggle(name: string) {
    setSelected((s) => (s.includes(name) ? s.filter((n) => n !== name) : [...s, name]));
  }

  async function handleRunSelected() {
    // Order follows the table, so the batch is reproducible from what was on screen.
    const names = (list.data ?? [])
      .map((e) => e.name)
      .filter((n) => selected.includes(n));
    await startQueue.mutateAsync({ experiment_names: names });
    setSelected([]);
  }

  async function handleRun(name: string) {
    // From the list, run the full experiment; subset selection lives in the
    // editor's Run dialog.
    const { session_id } = await start.mutateAsync({ experiment_name: name });
    navigate(`/runs/sessions/${session_id}`, { state: { experimentName: name } });
  }

  async function handleUploaded(parsed: Record<string, unknown>) {
    // Backend returns a resolved Experiment payload with `name` populated.
    const name = parsed.name as string;
    if (!name) return;
    await save.mutateAsync({ name, body: parsed });
    navigate(`/experiments/${name}`);
  }

  async function handleCreate(name: string) {
    setNewOpen(false);
    navigate(`/experiments/${name}`);
  }

  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={2} alignItems="center">
        <Typography variant="h5" sx={{ flexGrow: 1 }}>Experiments</Typography>
        {selected.length > 0 && (
          <Button
            variant="contained"
            size="small"
            color="secondary"
            disabled={queueRunning || startQueue.isPending}
            onClick={handleRunSelected}
          >
            Run {selected.length} selected
          </Button>
        )}
        <Button variant="contained" size="small" onClick={() => setNewOpen(true)}>
          + New
        </Button>
        <UploadYamlButton onUploaded={handleUploaded} />
      </Stack>

      {cost.data && cost.data.n_runs > 0 && (
        <Typography variant="body2" color="text.secondary">
          Estimated total spend:{" "}
          <strong>${cost.data.total_cost.toFixed(4)}</strong>{" "}
          across {cost.data.n_runs} run{cost.data.n_runs === 1 ? "" : "s"}
          {cost.data.n_runs_with_cost < cost.data.n_runs
            ? ` (${cost.data.n_runs_with_cost} priced; the rest free/unpriced)`
            : ""}
        </Typography>
      )}

      {queue.data && queue.data.items.length > 0 && (
        <Box sx={{ border: 1, borderColor: "divider", borderRadius: 1, p: 1.5 }}>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
            <Typography variant="subtitle2" sx={{ flexGrow: 1 }}>
              Queue — {queue.data.items.filter((i) => i.state === "completed").length}
              /{queue.data.items.length} done
              {queue.data.cancelled ? " (cancelling)" : ""}
            </Typography>
            {queueRunning && (
              <Button size="small" color="warning" onClick={() => cancelQueue.mutate()}>
                Cancel queue
              </Button>
            )}
          </Stack>
          {queueRunning && <LinearProgress sx={{ mb: 1 }} />}
          <Stack spacing={0.5}>
            {queue.data.items.map((it) => (
              <Stack key={it.name} direction="row" spacing={1} alignItems="center">
                <Chip
                  size="small"
                  label={it.state}
                  color={
                    it.state === "completed" ? "success"
                      : it.state === "running" ? "info"
                      : it.state === "failed" ? "error"
                      : "default"
                  }
                />
                {/* A queued run is an ordinary session, so it opens in the normal
                    live view — the queue is not a separate kind of run. */}
                {it.session_id ? (
                  <Link component={RouterLink} to={`/runs/sessions/${it.session_id}`}>
                    {it.name}
                  </Link>
                ) : (
                  <Typography variant="body2">{it.name}</Typography>
                )}
                {it.state === "running" && it.total_runs ? (
                  <Typography variant="caption" color="text.secondary">
                    run {(it.current_idx ?? 0) + 1}/{it.total_runs}
                  </Typography>
                ) : null}
                {it.error && (
                  <Typography variant="caption" color="error">{it.error}</Typography>
                )}
              </Stack>
            ))}
          </Stack>
        </Box>
      )}

      {list.isLoading && <CircularProgress />}
      {list.error && <Alert severity="error">Failed to load experiments.</Alert>}

      {list.data && (
        <Box sx={{ border: 1, borderColor: "divider", borderRadius: 1 }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell padding="checkbox" />
                <TableCell>Name</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Has runs</TableCell>
                <TableCell>Last run</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {list.data.map((e) => (
                <TableRow key={e.name} hover selected={selected.includes(e.name)}>
                  <TableCell padding="checkbox">
                    <Checkbox
                      size="small"
                      checked={selected.includes(e.name)}
                      disabled={!e.has_fixture || queueRunning}
                      onChange={() => toggle(e.name)}
                      inputProps={{ "aria-label": `select ${e.name}` }}
                    />
                  </TableCell>
                  <TableCell>
                    <Link component={RouterLink} to={`/runs/${e.name}`}>{e.name}</Link>
                  </TableCell>
                  <TableCell><StatusPill status={statusOf(e)} /></TableCell>
                  <TableCell>{e.has_runs ? "yes" : "—"}</TableCell>
                  <TableCell>{e.last_run_at ?? "—"}</TableCell>
                  <TableCell align="right">
                    <IconButton
                      size="small"
                      title="Results"
                      onClick={() => navigate(`/runs/${e.name}`)}
                      aria-label="results"
                    >
                      <AssessmentIcon fontSize="small" />
                    </IconButton>
                    <IconButton
                      size="small"
                      title="Run"
                      disabled={!e.has_fixture || start.isPending}
                      onClick={() => handleRun(e.name)}
                      aria-label="run"
                    >
                      <PlayArrowIcon fontSize="small" />
                    </IconButton>
                    <IconButton
                      size="small"
                      title="Edit"
                      onClick={() => navigate(`/experiments/${e.name}`)}
                      aria-label="edit"
                    >
                      <EditIcon fontSize="small" />
                    </IconButton>
                    <IconButton
                      size="small"
                      title="Delete"
                      onClick={() => setToDelete(e.name)}
                      aria-label="delete"
                    >
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      )}

      <NewExperimentDialog
        open={newOpen}
        onClose={() => setNewOpen(false)}
        onCreate={handleCreate}
      />

      <DeleteExperimentDialog
        open={toDelete !== null}
        name={toDelete ?? ""}
        busy={del.isPending}
        onClose={() => setToDelete(null)}
        onConfirm={async () => {
          if (toDelete) await del.mutateAsync(toDelete);
          setToDelete(null);
        }}
      />
    </Stack>
  );
}
