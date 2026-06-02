import { useEffect, useState } from "react";
import { Stack, TextField, Chip, Button, Box, Typography } from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import CancelIcon from "@mui/icons-material/Cancel";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import { useValidateModel } from "../api/queries";
import type { ValidateModelResp } from "../api/types";
import AddApiKeyDialog from "./AddApiKeyDialog";

interface Props {
  value: string;
  onChange: (value: string) => void;
  label?: string;
}

const DEBOUNCE_MS = 350;

export default function ModelValidationChip({ value, onChange, label = "Model" }: Props) {
  const [draft, setDraft] = useState(value);
  const [result, setResult] = useState<ValidateModelResp | null>(null);
  const [dlgOpen, setDlgOpen] = useState(false);
  const mut = useValidateModel();

  useEffect(() => { setDraft(value); }, [value]);

  useEffect(() => {
    if (!draft) { setResult(null); return; }
    const h = setTimeout(async () => {
      try { setResult(await mut.mutateAsync(draft)); }
      catch { setResult(null); }
    }, DEBOUNCE_MS);
    return () => clearTimeout(h);
  }, [draft]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Stack spacing={1}>
      <TextField
        label={label}
        size="small"
        value={draft}
        onChange={(e) => { setDraft(e.target.value); onChange(e.target.value); }}
        fullWidth
      />
      {result && (
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
          {result.status === "ok" && (
            <Chip size="small" color="success" icon={<CheckCircleIcon />} label="available" />
          )}
          {result.status === "model_not_found" && (
            <Chip size="small" color="warning" icon={<WarningAmberIcon />} label="not in catalog" />
          )}
          {result.status === "malformed" && (
            <Chip size="small" color="warning" icon={<WarningAmberIcon />}
                  label="malformed (expected provider/model)" />
          )}
          {result.status === "no_credentials" && (
            <>
              <Chip size="small" color="error" icon={<CancelIcon />} label="no key" />
              {result.provider && (
                <Button
                  size="small"
                  variant="outlined"
                  onClick={() => setDlgOpen(true)}
                >+ Add API key</Button>
              )}
            </>
          )}
        </Stack>
      )}
      {result?.suggestions && result.suggestions.length > 0 && (
        <Box>
          <Typography variant="caption" color="text.secondary">Did you mean:</Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap">
            {result.suggestions.map((s) => (
              <Chip
                key={s}
                size="small"
                label={s}
                onClick={() => { setDraft(s); onChange(s); }}
                clickable
              />
            ))}
          </Stack>
        </Box>
      )}
      <AddApiKeyDialog
        open={dlgOpen}
        provider={result?.provider ?? ""}
        onClose={() => setDlgOpen(false)}
        onSaved={() => {
          // Retrigger validation after saving the key.
          mut.mutateAsync(draft).then(setResult).catch(() => {});
        }}
      />
    </Stack>
  );
}
