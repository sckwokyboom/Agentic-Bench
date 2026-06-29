import { useEffect, useState } from "react";
import { TextField, InputAdornment, CircularProgress, Typography } from "@mui/material";
import { fetchModelContext } from "../api/queries";

interface ProviderLike { id?: string; base_url?: string; api_key_env?: string | null }
interface Props {
  value: number | null;
  onChange: (next: number | null) => void;
  label?: string;
  model?: string;
  providers?: ProviderLike[];
}

export default function ContextWindowField({
  value, onChange, label = "Model context window", model, providers = [],
}: Props) {
  const [auto, setAuto] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);

  const prefix = model?.includes("/") ? model.split("/")[0] : undefined;
  const provider = providers.find((p) => p.id === prefix);
  const baseUrl = provider?.base_url ?? "";

  useEffect(() => {
    let cancelled = false;
    if (!model || !baseUrl) { setAuto(null); return; }
    setLoading(true);
    fetchModelContext(model, baseUrl, provider?.api_key_env ?? null)
      .then((r) => { if (!cancelled) setAuto(r.context_window); })
      .catch(() => { if (!cancelled) setAuto(null); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [model, baseUrl, provider?.api_key_env]);

  // Prefill the field once when empty and a window was detected.
  useEffect(() => {
    if ((value === null || value === undefined) && auto != null) onChange(auto);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auto]);

  const helper = loading
    ? "Detecting from endpoint…"
    : auto != null
      ? `Auto-detected: ${auto.toLocaleString()} tokens (editable override)`
      : "Set manually, or configure the model's provider to auto-detect.";

  return (
    <TextField
      label={label}
      type="number"
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
      helperText={helper}
      fullWidth
      InputProps={{
        endAdornment: loading ? (
          <InputAdornment position="end"><CircularProgress size={16} /></InputAdornment>
        ) : auto != null ? (
          <InputAdornment position="end">
            <Typography variant="caption" color="text.secondary">auto {auto.toLocaleString()}</Typography>
          </InputAdornment>
        ) : undefined,
      }}
    />
  );
}
