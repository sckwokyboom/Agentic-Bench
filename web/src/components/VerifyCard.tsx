import { useState } from "react";
import { Card, CardContent, Stack, Typography, Chip, Button, Collapse, Box } from "@mui/material";
import type { Trace } from "../api/types";

interface Props { trace: Trace; }

export default function VerifyCard({ trace }: Props) {
  const [open, setOpen] = useState(false);
  const status = trace.verify_status;
  if (!status) return null;
  const passed = trace.verify_passed_count ?? 0;
  const failed = trace.verify_failed_count ?? 0;
  const total = passed + failed;
  const tone =
    status === "passed" ? "success.light"
    : status === "failed" ? "error.light"
    : "warning.light";

  return (
    <Card variant="outlined" sx={{ bgcolor: tone }}>
      <CardContent>
        <Stack direction="row" alignItems="center" spacing={1}>
          <Chip size="small" label={`🧪 ${status}`} />
          <Typography variant="body2">
            {passed}/{total} · {trace.verify_command} · {trace.verify_duration_s?.toFixed(1)}s
          </Typography>
          {trace.verify_failed_names.length > 0 && (
            <Button size="small" onClick={() => setOpen(!open)}>
              {open ? "hide failing ▴" : `show ${trace.verify_failed_names.length} failing ▾`}
            </Button>
          )}
        </Stack>
        <Collapse in={open}>
          <Box sx={{ mt: 1, fontFamily: "monospace", fontSize: 12 }}>
            {trace.verify_failed_names.map((n) => (
              <Typography key={n} variant="body2" color="error">— {n}</Typography>
            ))}
          </Box>
        </Collapse>
      </CardContent>
    </Card>
  );
}
