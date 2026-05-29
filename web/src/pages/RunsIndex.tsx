import { Link as RouterLink } from "react-router-dom";
import {
  Stack, Typography, CircularProgress, Alert, Box, Table, TableHead,
  TableBody, TableRow, TableCell, Link,
} from "@mui/material";
import { useExperiments } from "../api/queries";

export default function RunsIndex() {
  const list = useExperiments();
  const withRuns = (list.data ?? []).filter((e) => e.has_runs);

  return (
    <Stack spacing={2} sx={{ maxWidth: 900, mx: "auto" }}>
      <Typography variant="h5">Runs</Typography>
      {list.isLoading && <CircularProgress />}
      {list.error && <Alert severity="error">Failed to load experiments.</Alert>}
      {list.data && withRuns.length === 0 && (
        <Typography variant="body2" color="text.secondary">
          No runs yet — start one from Experiments.
        </Typography>
      )}
      {withRuns.length > 0 && (
        <Box sx={{ border: 1, borderColor: "divider", borderRadius: 1 }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>experiment</TableCell>
                <TableCell>last run</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {withRuns.map((e) => (
                <TableRow key={e.name} hover>
                  <TableCell>
                    <Link component={RouterLink} to={`/runs/${e.name}`}>{e.name}</Link>
                  </TableCell>
                  <TableCell>{e.last_run_at ?? "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      )}
    </Stack>
  );
}
