import { useNavigate } from "react-router-dom";
import {
  Alert,
  AlertTitle,
  Box,
  Button,
  Chip,
  Stack,
  Typography,
} from "@mui/material";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import { useActiveSessions } from "../api/queries";
import type { SessionSummary } from "../api/types";

function progressLabel(s: SessionSummary): string {
  // current_idx is the 1-based index of the run currently executing; it's 0
  // before the first run starts (e.g. during baseline verify), which can last a
  // while — show "starting…" rather than a confusing "run 0/N".
  const idx = Math.min(Math.max(s.current_idx, 0), s.total_runs);
  return s.total_runs > 0 && idx > 0 ? `run ${idx}/${s.total_runs}` : "starting…";
}

/**
 * A persistent banner (rendered under the app bar on every page) listing runs
 * that are currently in flight, each with an "Open live" button. This is the
 * way back to a live trace after the run tab was closed or the page reloaded —
 * the websocket replays the buffered events so the trace resumes mid-run.
 */
export default function ActiveRunsBanner() {
  const navigate = useNavigate();
  const { data } = useActiveSessions();
  const active = (data ?? []).filter(
    (s) => s.state === "running" || s.state === "pending",
  );
  if (active.length === 0) return null;

  return (
    <Box sx={{ px: 3, pt: 2 }}>
      <Alert severity="info" icon={false}>
        <AlertTitle>
          {active.length === 1
            ? "A run is in progress"
            : `${active.length} runs in progress`}
        </AlertTitle>
        <Stack spacing={1}>
          {active.map((s) => (
            <Stack
              key={s.session_id}
              direction="row"
              spacing={1.5}
              alignItems="center"
              flexWrap="wrap"
            >
              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                {s.experiment_name}
              </Typography>
              <Chip size="small" label={progressLabel(s)} color="info" />
              {s.current_condition && (
                <Chip
                  size="small"
                  variant="outlined"
                  label={
                    s.current_rep != null
                      ? `${s.current_condition} · rep ${s.current_rep}`
                      : s.current_condition
                  }
                />
              )}
              <Box sx={{ flexGrow: 1 }} />
              <Button
                size="small"
                variant="outlined"
                startIcon={<OpenInNewIcon />}
                onClick={() =>
                  navigate(`/runs/sessions/${s.session_id}`, {
                    state: { experimentName: s.experiment_name },
                  })
                }
              >
                Open live
              </Button>
            </Stack>
          ))}
        </Stack>
      </Alert>
    </Box>
  );
}
