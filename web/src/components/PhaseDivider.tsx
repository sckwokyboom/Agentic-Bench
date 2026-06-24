import { Stack, Typography, Box } from "@mui/material";

// Phased-orchestration phase labels, shared by the live stream (EventStream) and
// the finished-trace view (TraceView) so both render phase bands identically.
export const PHASE_LABEL: Record<string, string> = {
  understand: "1 · understand",
  plan: "2 · plan",
  implement: "3 · implement",
  diagnose: "4 · diagnose",
};

export default function PhaseDivider({ phase }: { phase: string }) {
  return (
    <Stack direction="row" alignItems="center" spacing={1} sx={{ mt: 1 }}>
      <Typography variant="overline" color="text.secondary">
        {PHASE_LABEL[phase] ?? phase}
      </Typography>
      <Box sx={{ flexGrow: 1, height: "1px", bgcolor: "divider" }} />
    </Stack>
  );
}
