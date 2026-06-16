import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Stack, Box, Typography, Button, Table, TableHead, TableBody, TableRow,
  TableCell, IconButton, CircularProgress, Alert, Link,
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
  const save = useSaveExperiment();
  const [toDelete, setToDelete] = useState<string | null>(null);
  const [newOpen, setNewOpen] = useState(false);

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
        <Button variant="contained" size="small" onClick={() => setNewOpen(true)}>
          + New
        </Button>
        <UploadYamlButton onUploaded={handleUploaded} />
      </Stack>

      {list.isLoading && <CircularProgress />}
      {list.error && <Alert severity="error">Failed to load experiments.</Alert>}

      {list.data && (
        <Box sx={{ border: 1, borderColor: "divider", borderRadius: 1 }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Name</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Has runs</TableCell>
                <TableCell>Last run</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {list.data.map((e) => (
                <TableRow key={e.name} hover>
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
