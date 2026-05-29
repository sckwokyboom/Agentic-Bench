import { useState } from "react";
import { Dialog, DialogTitle, DialogContent, DialogActions, TextField, Button } from "@mui/material";

interface Props {
  open: boolean;
  onClose: () => void;
  onCreate: (name: string) => void;
}

export default function NewExperimentDialog({ open, onClose, onCreate }: Props) {
  const [name, setName] = useState("");
  const valid = /^[a-z0-9][a-z0-9_-]*$/.test(name);
  return (
    <Dialog open={open} onClose={onClose}>
      <DialogTitle>New experiment</DialogTitle>
      <DialogContent>
        <TextField
          autoFocus
          fullWidth
          label="Name"
          helperText="kebab/snake-case, ascii only"
          value={name}
          onChange={(e) => setName(e.target.value)}
          error={name.length > 0 && !valid}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          disabled={!valid}
          onClick={() => { onCreate(name); setName(""); }}
        >Create</Button>
      </DialogActions>
    </Dialog>
  );
}
