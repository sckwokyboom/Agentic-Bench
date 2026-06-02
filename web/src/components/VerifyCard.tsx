import { useEffect, useState } from "react";
import {
  Card, CardContent, Stack, Typography, Chip, Button, Collapse, Box, Dialog,
  DialogTitle, DialogContent, CircularProgress,
} from "@mui/material";
import { alpha } from "@mui/material/styles";
import { useQueryClient } from "@tanstack/react-query";
import { useVerifyLog, useStartReverify, useReverifyStatus } from "../api/queries";
import { buildSystemLabel } from "../lib/buildSystem";
import { selectable } from "../theme";
import type { Trace } from "../api/types";

interface Props {
  trace: Trace;
  name: string;
  condition: string;
  rep: number;
  batch?: string;
}

export default function VerifyCard({ trace, name, condition, rep, batch }: Props) {
  const [open, setOpen] = useState(false);
  const [logOpen, setLogOpen] = useState(false);
  const log = useVerifyLog(name, condition, rep, logOpen, batch);

  const qc = useQueryClient();
  const start = useStartReverify();
  const [verifyId, setVerifyId] = useState<string | null>(null);
  const job = useReverifyStatus(verifyId);
  // `verifyId !== null` keeps the button disabled in the one render between the
  // POST resolving and the first poll, so a fast double-click can't start a 2nd job.
  const running = start.isPending || verifyId !== null || job.data?.state === "running";

  useEffect(() => {
    if (job.data?.state === "done" || job.data?.state === "error") {
      // Bare prefixes so every batch variant (incl. newest "") is invalidated.
      qc.invalidateQueries({ queryKey: ["trace", name, condition, rep] });
      qc.invalidateQueries({ queryKey: ["metrics", name, condition, rep] });
      qc.invalidateQueries({ queryKey: ["verifyLog", name, condition, rep] });
      setVerifyId(null);
    }
  }, [job.data?.state, qc, name, condition, rep]);

  async function handleReverify() {
    const { verify_id } = await start.mutateAsync({ name, condition, rep });
    setVerifyId(verify_id);
  }

  const status = trace.verify_status;
  if (!status) return null;
  const passed = trace.verify_passed_count ?? 0;
  const failed = trace.verify_failed_count ?? 0;
  const total = passed + failed;
  const toneColor: "success" | "error" | "warning" =
    status === "passed" ? "success" : status === "failed" ? "error" : "warning";
  const headline = trace.verify_message || status;

  return (
    <Card
      variant="outlined"
      sx={{
        bgcolor: (th) => alpha(th.palette[toneColor].main, th.palette.mode === "dark" ? 0.18 : 0.1),
        borderColor: (th) => alpha(th.palette[toneColor].main, 0.4),
      }}
    >
      <CardContent>
        <Stack direction="row" alignItems="center" spacing={1} flexWrap="wrap">
          <Chip size="small" label={`🧪 ${status}`} />
          {trace.verify_reason && trace.verify_reason !== status && (
            <Chip size="small" variant="outlined" label={trace.verify_reason} />
          )}
          <Typography variant="body2">{headline}</Typography>
          <Box sx={{ flexGrow: 1 }} />
          <Button size="small" onClick={handleReverify} disabled={running}>
            {running ? "Re-verifying…" : "Re-verify"}
          </Button>
          <Button size="small" onClick={() => setLogOpen(true)}>View verify output</Button>
        </Stack>

        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
          {buildSystemLabel(trace.verify_command)} · <code>{trace.verify_command ?? "—"}</code>
          {total > 0 && <> · {passed}/{total} passed</>}
          {trace.verify_duration_s != null && <> · {trace.verify_duration_s.toFixed(1)}s</>}
        </Typography>

        {trace.verify_failed_names.length > 0 && (
          <>
            <Button size="small" onClick={() => setOpen(!open)} sx={{ mt: 1 }}>
              {open ? "hide failing ▴" : `show ${trace.verify_failed_names.length} failing ▾`}
            </Button>
            <Collapse in={open}>
              <Box sx={{ mt: 1, fontFamily: "monospace", fontSize: 12, ...selectable }}>
                {trace.verify_failed_names.map((n) => (
                  <Typography key={n} variant="body2" color="error">— {n}</Typography>
                ))}
              </Box>
            </Collapse>
          </>
        )}

        <Dialog open={logOpen} onClose={() => setLogOpen(false)} maxWidth="md" fullWidth>
          <DialogTitle>verify_output.log</DialogTitle>
          <DialogContent>
            {log.isLoading && <CircularProgress size={20} />}
            {log.error && <Typography color="error">No verify log for this run.</Typography>}
            {log.data != null && (
              <Box
                component="pre"
                sx={{
                  m: 0, whiteSpace: "pre-wrap", fontFamily: "monospace", fontSize: 12,
                  bgcolor: "#0e1116", color: "#dbe1ec", borderRadius: 1, p: 1.5,
                  maxHeight: 480, overflow: "auto", userSelect: "text",
                }}
              >
                {log.data}
              </Box>
            )}
          </DialogContent>
        </Dialog>
      </CardContent>
    </Card>
  );
}
