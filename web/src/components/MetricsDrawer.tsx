import { useState } from "react";
import {
  Drawer, IconButton, Box, Typography, Divider, Stack, Tooltip,
} from "@mui/material";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import { useMetrics } from "../api/queries";

interface Props {
  name: string;
  condition: string;
  rep: number;
  batch?: string;
}

export default function MetricsDrawer({ name, condition, rep, batch }: Props) {
  const [open, setOpen] = useState(false);
  const metrics = useMetrics(name, condition, rep, batch);
  return (
    <>
      <Tooltip title="Metrics">
        <IconButton
          color="primary"
          onClick={() => setOpen(true)}
          sx={{ position: "fixed", right: 16, top: 80 }}
        >
          <OpenInNewIcon />
        </IconButton>
      </Tooltip>
      <Drawer anchor="right" open={open} onClose={() => setOpen(false)}>
        <Box sx={{ width: 360, p: 2 }}>
          <Typography variant="h6">Metrics</Typography>
          <Divider sx={{ my: 1 }} />
          {metrics.isLoading && <Typography variant="body2">loading…</Typography>}
          {metrics.data && (
            <Stack spacing={1} sx={{ fontFamily: "monospace", fontSize: 12 }}>
              {Object.entries(metrics.data).map(([k, v]) => (
                <Box key={k}>
                  <Typography variant="caption" color="text.secondary">{k}</Typography>
                  <Typography variant="body2" sx={{ wordBreak: "break-all" }}>
                    {typeof v === "object" ? JSON.stringify(v) : String(v)}
                  </Typography>
                </Box>
              ))}
            </Stack>
          )}
        </Box>
      </Drawer>
    </>
  );
}
