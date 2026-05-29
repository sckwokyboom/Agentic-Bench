import { useState } from "react";
import {
  Dialog, DialogTitle, DialogContent, DialogActions,
  TextField, Button, Typography,
} from "@mui/material";
import { useWriteProviderCredentials } from "../api/queries";

interface Props {
  open: boolean;
  provider: string;
  onClose: () => void;
  onSaved: () => void;
}

export default function AddApiKeyDialog({ open, provider, onClose, onSaved }: Props) {
  const [key, setKey] = useState("");
  const mut = useWriteProviderCredentials();
  return (
    <Dialog open={open} onClose={onClose}>
      <DialogTitle>Add API key for {provider}</DialogTitle>
      <DialogContent>
        <Typography variant="body2" gutterBottom>
          The key is written to <code>~/.local/share/opencode/auth.json</code>
          {" "}on this machine. No network call.
        </Typography>
        <TextField
          autoFocus fullWidth type="password" label="API key"
          value={key} onChange={(e) => setKey(e.target.value)}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          disabled={key.length === 0 || mut.isPending}
          onClick={async () => {
            await mut.mutateAsync({ provider, api_key: key });
            setKey("");
            onSaved();
            onClose();
          }}
        >Save</Button>
      </DialogActions>
    </Dialog>
  );
}
