import { Alert, AlertTitle, Typography, Box } from "@mui/material";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";

const inlineIcon = { fontSize: "inherit", verticalAlign: "middle", mr: 0.5 } as const;

interface Props {
  nServiceErrors?: number;
  interruptedReason?: string | null;
  serviceErrorMessages?: string[];
  verifyInsensitive?: boolean;
}

// Presentational-only: surfaces the three validity signals (service/proxy
// errors, an interrupted run, an insensitive verify) so a run that scored
// without doing real work cannot look like a clean pass. Renders nothing when
// none of the signals fire (extracted from TraceView to keep it unit-testable).
export default function ValiditySignals({
  nServiceErrors = 0,
  interruptedReason = null,
  serviceErrorMessages = [],
  verifyInsensitive = false,
}: Props) {
  const hasErrors = nServiceErrors > 0 || Boolean(interruptedReason);
  if (!hasErrors && !verifyInsensitive) return null;

  const shownMessages = serviceErrorMessages.slice(0, 3);

  return (
    <>
      {hasErrors && (
        <Alert severity="error" icon={<ErrorOutlineIcon />}>
          <AlertTitle>
            {nServiceErrors > 0
              ? `${nServiceErrors} service/proxy error${nServiceErrors === 1 ? "" : "s"} during this run`
              : "This run was interrupted"}
          </AlertTitle>
          <Typography variant="body2">
            {interruptedReason && <>Interrupted: <code>{interruptedReason}</code>. </>}
            Open the run log below for the raw provider/proxy output.
          </Typography>
          {shownMessages.length > 0 && (
            <Box sx={{ mt: 1, fontFamily: "monospace", fontSize: 12 }}>
              {shownMessages.map((m, i) => (
                <Typography key={i} variant="body2" component="div" sx={{ wordBreak: "break-word" }}>
                  — {m}
                </Typography>
              ))}
            </Box>
          )}
        </Alert>
      )}
      {verifyInsensitive && (
        <Alert severity="warning" icon={<WarningAmberIcon />}>
          <AlertTitle>Verify can't distinguish agent work</AlertTitle>
          <Typography variant="body2">
            The stripped fixture already passes these tests, so pass/fail counts
            aren't meaningful for this task.
          </Typography>
        </Alert>
      )}
    </>
  );
}
