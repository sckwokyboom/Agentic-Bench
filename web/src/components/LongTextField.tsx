import { useState } from "react";
import {
  TextField, IconButton, InputAdornment, Dialog, DialogTitle,
  DialogContent, DialogActions, Button, Tooltip,
} from "@mui/material";
import OpenInFullIcon from "@mui/icons-material/OpenInFull";

interface Props {
  value: string;
  onChange: (next: string) => void;
  label?: string;
  helperText?: string;
  rows?: number;
}

export default function LongTextField({
  value, onChange, label = "Text", helperText, rows = 6,
}: Props) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <TextField
        label={label}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        helperText={helperText}
        multiline
        minRows={rows}
        maxRows={rows}
        fullWidth
        InputProps={{
          endAdornment: (
            <InputAdornment position="end" sx={{ alignSelf: "flex-start", mt: 1 }}>
              <Tooltip title="Expand">
                <IconButton size="small" onClick={() => setOpen(true)}>
                  <OpenInFullIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </InputAdornment>
          ),
        }}
      />
      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="md">
        <DialogTitle>{label}</DialogTitle>
        <DialogContent>
          <TextField
            value={value ?? ""}
            onChange={(e) => onChange(e.target.value)}
            multiline
            minRows={20}
            fullWidth
            autoFocus
            inputProps={{ "aria-label": label }}
            sx={{ mt: 1 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>Done</Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
