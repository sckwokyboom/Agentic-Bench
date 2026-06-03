import { useState } from "react";
import {
  Dialog, DialogTitle, DialogContent, DialogActions,
  TextField, Button, Stack,
} from "@mui/material";

export interface CustomEndpointInput {
  id: string;
  baseUrl: string;
  model: string;
  apiKey: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  onAdd: (input: CustomEndpointInput) => void;
}

/**
 * Presentational dialog for wiring an OpenAI-compatible endpoint. Holds no data
 * writes itself — on Add it hands the four fields to `onAdd` and closes.
 */
export default function CustomEndpointDialog({ open, onClose, onAdd }: Props) {
  const [id, setId] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");

  function reset() {
    setId("");
    setBaseUrl("");
    setModel("");
    setApiKey("");
  }

  function handleClose() {
    reset();
    onClose();
  }

  const canAdd =
    id.trim().length > 0 && baseUrl.trim().length > 0 && model.trim().length > 0;

  function handleAdd() {
    onAdd({ id: id.trim(), baseUrl: baseUrl.trim(), model: model.trim(), apiKey });
    reset();
    onClose();
  }

  return (
    <Dialog open={open} onClose={handleClose} fullWidth maxWidth="sm">
      <DialogTitle>Add custom OpenAI endpoint</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField
            autoFocus
            fullWidth
            label="Provider id"
            placeholder="myllm"
            helperText="becomes the Model prefix: <id>/<model>"
            value={id}
            onChange={(e) => setId(e.target.value)}
          />
          <TextField
            fullWidth
            label="Base URL"
            placeholder="http://10.0.0.5:8000/v1"
            helperText="OpenAI-compatible base; include the path your server expects (usually /v1). Leave key blank for keyless endpoints."
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
          />
          <TextField
            fullWidth
            label="Model name"
            placeholder="my-model"
            value={model}
            onChange={(e) => setModel(e.target.value)}
          />
          <TextField
            fullWidth
            type="password"
            label="API key"
            helperText="Optional. Stored in opencode auth.json on this machine; leave blank if the endpoint needs no key."
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>Cancel</Button>
        <Button variant="contained" disabled={!canAdd} onClick={handleAdd}>
          Add
        </Button>
      </DialogActions>
    </Dialog>
  );
}
