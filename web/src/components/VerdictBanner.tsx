import { Alert, Typography } from "@mui/material";
import type { Trace } from "../api/types";

interface Props { trace: Trace; }

export default function VerdictBanner({ trace }: Props) {
  const v = trace.verify_status;
  if (v === "passed") {
    return (
      <Alert severity="success">
        <Typography variant="subtitle1">
          ✓ Verified — {trace.verify_passed_count}/{trace.verify_passed_count} tests passed
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {trace.verify_command} · {trace.verify_duration_s?.toFixed(1)}s
        </Typography>
      </Alert>
    );
  }
  if (v === "failed") {
    const total = (trace.verify_passed_count ?? 0) + (trace.verify_failed_count ?? 0);
    return (
      <Alert severity="error">
        <Typography variant="subtitle1">
          ✗ Verify failed — {trace.verify_passed_count}/{total}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {trace.verify_command} · {trace.verify_duration_s?.toFixed(1)}s
        </Typography>
      </Alert>
    );
  }
  if (v === "skipped") return <Alert severity="info">Verify skipped.</Alert>;
  if (v === "timeout") return <Alert severity="warning">Verify timed out after {trace.verify_duration_s?.toFixed(0)}s.</Alert>;
  if (v === "error") return <Alert severity="warning">Verify errored — see verify_output.log.</Alert>;
  return <Alert severity="info">No verify result.</Alert>;
}
