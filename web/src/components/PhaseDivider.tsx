import { Stack, Typography, Box } from "@mui/material";

// Phased-orchestration phase labels, shared by the live stream (EventStream) and
// the finished-trace view (TraceView) so both render phase bands identically.
export const PHASE_LABEL: Record<string, string> = {
  understand: "1 · understand",
  plan: "2 · plan",
  implement: "3 · implement",
  diagnose: "4 · diagnose",
};

// What the controller does in each phase — shown under the band so the trace is
// self-explanatory: who sets the task (the controller's prompt) vs who does the
// work (the agent), and what the controller checks afterwards.
const PHASE_DESC: Record<string, string> = {
  understand:
    "Controller prompts the agent to study the target method — read its callers + a spread of tests — and write a CONTRACT of required behaviour (read/grep only, no edits). The agent writes the contract; the controller then gates it (long enough, addresses the required aspects, read enough sources).",
  plan:
    "Controller prompts the agent to sketch an approach naming the concrete existing helpers it will use (read-only). The agent writes the plan; the controller gates it (non-empty).",
  implement:
    "Controller prompts the agent to implement the method to satisfy the contract (read + edit), then runs the test suite itself and keeps the change only if it improved over the baseline.",
  diagnose:
    "Controller clusters the remaining test failures, gives the agent one example per cluster and asks for ONE root-cause fix (read + edit + verify), re-runs the suite, and accepts the change or reverts to the best version so far.",
};

export default function PhaseDivider({ phase }: { phase: string }) {
  const desc = PHASE_DESC[phase];
  return (
    <Stack spacing={0.25} sx={{ mt: 1 }}>
      <Stack direction="row" alignItems="center" spacing={1}>
        <Typography variant="overline" color="text.secondary">
          {PHASE_LABEL[phase] ?? phase}
        </Typography>
        <Box sx={{ flexGrow: 1, height: "1px", bgcolor: "divider" }} />
      </Stack>
      {desc && (
        <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
          {desc}
        </Typography>
      )}
    </Stack>
  );
}
