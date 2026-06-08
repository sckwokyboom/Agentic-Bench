import { Alert, AlertTitle, Typography, Box } from "@mui/material";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import GavelIcon from "@mui/icons-material/Gavel";
import type { CheatingReport } from "../api/types";

export const CHEATING_LABELS: Record<string, string> = {
  network: "fetched the network / upstream repo",
  vcs_history: "read VCS history to recover the original (git log/show/.git)",
  outside_workdir: "read source files outside the run workdir",
  fs_wide_search: "ran a filesystem-wide search",
  output_matches_original: "final method body is near-identical to the reference original (possible copy)",
};

interface Props {
  nServiceErrors?: number;
  interruptedReason?: string | null;
  serviceErrorMessages?: string[];
  verifyInsensitive?: boolean;
  cheating?: CheatingReport | null;
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
  cheating = null,
}: Props) {
  const hasErrors = nServiceErrors > 0 || Boolean(interruptedReason);
  const suspicious = cheating?.verdict === "suspicious" && (cheating?.signals?.length ?? 0) > 0;
  if (!hasErrors && !verifyInsensitive && !suspicious) return null;

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
      {suspicious && (
        <Alert severity="warning" icon={<GavelIcon />}>
          <AlertTitle>Possible cheating — review this run</AlertTitle>
          <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
            {cheating!.signals.map((s) => (
              <li key={s.type}>
                <Typography variant="body2" component="span">
                  {CHEATING_LABELS[s.type] ?? s.type}
                </Typography>
                {s.evidence?.length > 0 && (
                  <Box sx={{ fontFamily: "monospace", fontSize: 12, color: "text.secondary" }}>
                    {s.evidence.slice(0, 3).map((e, i) => (
                      <div key={i} style={{ wordBreak: "break-word" }}>— {e}</div>
                    ))}
                  </Box>
                )}
              </li>
            ))}
          </Box>
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
