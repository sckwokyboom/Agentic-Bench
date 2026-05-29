import { useNavigate, useParams, Link as RouterLink } from "react-router-dom";
import {
  Stack, Typography, CircularProgress, Alert, Button, Box, Link,
} from "@mui/material";
import { useRuns, useRunsSummary } from "../api/queries";
import SummaryTable from "../components/SummaryTable";
import RunsTable from "../components/RunsTable";

export default function ExperimentResults() {
  const { name } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const runs = useRuns(name);
  const summary = useRunsSummary(name);

  return (
    <Stack spacing={3} sx={{ maxWidth: 1100, mx: "auto" }}>
      <Stack direction="row" alignItems="center" spacing={2}>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>Results · {name}</Typography>
        <Button component={RouterLink} to={`/experiments/${name}`} variant="outlined" size="small">
          Edit
        </Button>
      </Stack>

      <Box>
        <Typography variant="subtitle2" gutterBottom>Aggregate (baseline vs augmented)</Typography>
        {summary.isLoading && <CircularProgress size={20} />}
        {summary.error && <Alert severity="error">Failed to load summary.</Alert>}
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
