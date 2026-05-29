import { Card, CardContent, Typography, Stack } from "@mui/material";
import { computePlan, type MiniExperiment } from "../lib/computePlan";
import { formatDuration } from "../lib/formatDuration";

interface Props { formData: Partial<MiniExperiment>; }

export default function PlanPanel({ formData }: Props) {
  const mini: MiniExperiment = {
    conditions: (formData.conditions ?? []) as { name: string }[],
    reps_per_condition: formData.reps_per_condition ?? 0,
    timeout_s: formData.timeout_s ?? 0,
  };
  const plan = computePlan(mini);
  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="subtitle2" gutterBottom>Plan</Typography>
        <Stack spacing={0.5}>
          <Typography variant="body2">
            {mini.conditions.length} × {mini.reps_per_condition} = <b>{plan.total_runs}</b> runs
          </Typography>
          <Typography variant="body2" color="text.secondary">
            est. {formatDuration(plan.eta_seconds)} at {mini.timeout_s}s/run timeout
          </Typography>
        </Stack>
      </CardContent>
    </Card>
  );
}
