import { useState } from "react";
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button,
  FormGroup, FormControlLabel, Checkbox, TextField, Stack, Typography,
} from "@mui/material";

interface Props {
  open: boolean;
  conditions: string[];
  defaultReps: number;
  running: boolean;
  onClose: () => void;
  onStart: (opts: { conditions: string[]; repetitions: number }) => void;
}

// Lets the user run a SUBSET of an experiment — pick which conditions and how
// many repetitions — instead of always running the full N×M matrix. Mount it
// only while open (parent gates with `{open && <RunOptionsDialog .../>}`) so the
// selection re-seeds from the current experiment each time.
export default function RunOptionsDialog({
  open, conditions, defaultReps, running, onClose, onStart,
}: Props) {
  const [checked, setChecked] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(conditions.map((c) => [c, true])));
  const [reps, setReps] = useState(String(defaultReps));

  const selected = conditions.filter((c) => checked[c]);
  const repsN = Math.max(1, Math.floor(Number(reps) || 0));
  const canStart = selected.length > 0 && !running;

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>Run options</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 0.5 }}>
          <Typography variant="caption" color="text.secondary">
            Run a subset — pick conditions and repetitions.
          </Typography>
          <FormGroup>
            {conditions.map((c) => (
              <FormControlLabel
                key={c}
                control={
                  <Checkbox
                    checked={!!checked[c]}
                    onChange={(e) =>
                      setChecked((s) => ({ ...s, [c]: e.target.checked }))}
                  />
                }
                label={c}
              />
            ))}
          </FormGroup>
          <TextField
            label="Repetitions"
            type="number"
            size="small"
            value={reps}
            onChange={(e) => setReps(e.target.value)}
            inputProps={{ min: 1 }}
            sx={{ maxWidth: 160 }}
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          color="success"
          disabled={!canStart}
          onClick={() => onStart({ conditions: selected, repetitions: repsN })}
        >
          {running ? "Starting…" : "Start run"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
