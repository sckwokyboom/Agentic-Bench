import { useEffect, useRef, useState } from "react";
import { Paper, Stack, CircularProgress, Typography, Box, IconButton, Tooltip } from "@mui/material";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import CheckIcon from "@mui/icons-material/Check";
import { selectable } from "../theme";
import { copyText } from "../lib/clipboard";
import type { StartupStatus as Status } from "../lib/startupStatus";

function fmtElapsed(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return m > 0 ? `${m}:${String(s).padStart(2, "0")}` : `${s}s`;
}

interface Props {
  status: Status;
}

/**
 * A prominent "loading" banner shown during the silent startup window so the
 * user can see the run is alive and what stage it's in (baseline verify,
 * workdir prep, waiting for the model, 429 backoff) plus how long it's taken.
 * The elapsed timer resets whenever the phase message changes.
 */
export default function StartupStatus({ status }: Props) {
  const [elapsedMs, setElapsedMs] = useState(0);
  const startRef = useRef<number>(Date.now());

  useEffect(() => {
    startRef.current = Date.now();
    setElapsedMs(0);
    const id = setInterval(() => {
      setElapsedMs(Date.now() - startRef.current);
    }, 1000);
    return () => clearInterval(id);
  }, [status.message]);

  const retryHint =
    status.kind === "rate_limit_backoff" && status.retry != null
      ? ` · retry ${status.retry}${status.maxRetries != null ? `/${status.maxRetries}` : ""}`
      : "";

  const isError = status.kind === "model_error";

  const [copied, setCopied] = useState(false);
  async function onCopy() {
    if (await copyText(status.message)) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  }

  return (
    <Paper variant="outlined"
           sx={{ p: 1.5, borderColor: isError ? "error.main" : "primary.light" }}>
      <Stack direction="row" alignItems="center" spacing={1.5}>
        {isError ? <ErrorOutlineIcon color="error" /> : <CircularProgress size={20} />}
        <Box sx={{ flexGrow: 1, minWidth: 0 }}>
          <Typography variant="body2" color={isError ? "error" : undefined}
                      sx={{ ...selectable, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
            {status.message}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {fmtElapsed(elapsedMs)} elapsed{retryHint}
          </Typography>
        </Box>
        {isError && (
          <Tooltip title={copied ? "Copied" : "Copy"}>
            <IconButton aria-label="copy error message" size="small" onClick={onCopy}>
              {copied ? <CheckIcon fontSize="small" /> : <ContentCopyIcon fontSize="small" />}
            </IconButton>
          </Tooltip>
        )}
      </Stack>
    </Paper>
  );
}
