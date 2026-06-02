import { Card, CardContent, Stack, Typography, Button, Chip } from "@mui/material";

interface Props {
  name: string;
  formData: Record<string, unknown>;
  canRun: boolean;
  running: boolean;
  onRun: () => void;
  onEdit: () => void;
}

/**
 * Shown in place of the form right after a successful save: a clear "saved"
 * confirmation + a compact config summary + the natural next step (run the
 * experiment), with a way back to editing.
 */
export default function SavedExperimentCard({
  name, formData, canRun, running, onRun, onEdit,
}: Props) {
  const conditions = Array.isArray(formData.conditions) ? formData.conditions.length : 0;
  const reps = typeof formData.repetitions === "number" ? formData.repetitions : null;
  const model = typeof formData.model === "string" && formData.model ? formData.model : "—";

  return (
    <Card variant="outlined" data-testid="saved-card">
      <CardContent>
        <Stack spacing={2}>
          <Stack direction="row" spacing={1} alignItems="baseline" flexWrap="wrap">
            <Typography variant="h6" color="success.main">✓ Saved</Typography>
            <Typography variant="body2" color="text.secondary">
              Configuration for <b>{name}</b> was written to disk.
            </Typography>
          </Stack>

          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Chip size="small" variant="outlined" label={`model: ${model}`} />
            <Chip size="small" variant="outlined" label={`${conditions} conditions`} />
            {reps != null && <Chip size="small" variant="outlined" label={`${reps} reps`} />}
            {reps != null && (
              <Chip size="small" variant="outlined" label={`${conditions * reps} runs`} />
            )}
          </Stack>

          <Stack direction="row" spacing={1}>
            <Button
              variant="contained"
              color="success"
              onClick={onRun}
              disabled={!canRun || running}
              startIcon={<span aria-hidden>▶</span>}
            >
              {running ? "Starting…" : "Run experiment"}
            </Button>
            <Button variant="outlined" onClick={onEdit}>Edit again</Button>
          </Stack>

          {!canRun && (
            <Typography variant="caption" color="warning.main">
              Add a fixture to this experiment to enable running.
            </Typography>
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}
