import { Dialog, DialogTitle, DialogContent, DialogActions, Button, Typography } from "@mui/material";

interface Props {
  open: boolean;
  name: string;
  busy?: boolean;
  onClose: () => void;
  onConfirm: () => void;
}

export default function DeleteExperimentDialog({ open, name, busy = false, onClose, onConfirm }: Props) {
  return (
    <Dialog open={open} onClose={onClose}>
      <DialogTitle>Delete "{name}"?</DialogTitle>
      <DialogContent>
        <Typography>
          This removes the experiment directory including prompts, slices, and run history.
          The action is irreversible.
        </Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button color="error" variant="contained" onClick={onConfirm} disabled={busy}>Delete</Button>
      </DialogActions>
    </Dialog>
  );
}
