import { useEffect, useState } from "react";
import { Stack, TextField, Chip, Button, Box, Typography, Autocomplete, createFilterOptions } from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import CancelIcon from "@mui/icons-material/Cancel";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import HelpOutlineIcon from "@mui/icons-material/HelpOutline";
import AddLinkIcon from "@mui/icons-material/AddLink";
import VpnKeyIcon from "@mui/icons-material/VpnKey";
import { useValidateModel, useModelCatalog, useRuntimeMode } from "../api/queries";
import type { ValidateModelResp, ModelCatalogEntry } from "../api/types";
import AddApiKeyDialog from "./AddApiKeyDialog";
import CustomEndpointDialog, { type CustomEndpointInput } from "./CustomEndpointDialog";

interface Props {
  value: string;
  onChange: (value: string) => void;
  label?: string;
  onAddCustomEndpoint?: (input: CustomEndpointInput) => void;
}

// Pinned action row appended to the bottom of the dropdown. Its `id` is a
// sentinel that must never be submitted as a model value.
const ADD_CUSTOM: ModelCatalogEntry = { provider: "", id: "__add_custom_endpoint__" };
const isAddCustom = (o: ModelCatalogEntry | string): boolean =>
  typeof o !== "string" && o.id === ADD_CUSTOM.id;

const catalogFilter = createFilterOptions<ModelCatalogEntry>();

const DEBOUNCE_MS = 350;

export default function ModelValidationChip({ value, onChange, label = "Model", onAddCustomEndpoint }: Props) {
  const [draft, setDraft] = useState(value);
  const [result, setResult] = useState<ValidateModelResp | null>(null);
  const [dlgOpen, setDlgOpen] = useState(false);
  const [endpointOpen, setEndpointOpen] = useState(false);
  const mut = useValidateModel();
  const catalog = useModelCatalog();
  // Exposed/LAN mode: the key is per-session (not shared/persisted) — reflect that
  // in the key affordance so visitors know to enter their own.
  const isolated = !!useRuntimeMode().data?.isolated;
  const options: ModelCatalogEntry[] = catalog.data ?? [];
  // Provider parsed straight from the model id (e.g. "deepseek/…" → "deepseek")
  // so the API-key action is ALWAYS available — not gated behind the advisory
  // validate status (which is unreliable for custom providers).
  const modelProvider = (draft.split("/")[0] || "").trim();

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
      <Autocomplete<ModelCatalogEntry, false, false, true>
        freeSolo
        fullWidth
        options={options}
        // Run the default filter over real catalog entries, then ALWAYS pin the
        // add-custom action at the bottom — regardless of the typed text.
        filterOptions={(opts, state) => [...catalogFilter(opts, state), ADD_CUSTOM]}
        getOptionLabel={(o) =>
          typeof o === "string" ? o : isAddCustom(o) ? "" : o.id
        }
        groupBy={(o) => (typeof o === "string" ? "" : isAddCustom(o) ? "Custom" : o.provider)}
        renderOption={(props, o) =>
          isAddCustom(o) ? (
            <Box component="li" {...props} key="__add_custom_endpoint__">
              <AddLinkIcon fontSize="small" sx={{ mr: 1 }} />
              <Typography component="span" sx={{ fontWeight: 600 }}>
                Add custom OpenAI endpoint…
              </Typography>
            </Box>
          ) : (
            <Box component="li" {...props} key={typeof o === "string" ? o : o.id}>
              {typeof o === "string" ? o : o.id}
            </Box>
          )
        }
        inputValue={draft}
        onInputChange={(_, v, reason) => {
          // Selecting the sentinel ("Add custom endpoint…", label "") makes MUI
          // fire a reset-to-empty — that must NOT wipe an existing model value.
          // A real option's reset sets v to its (non-empty) id; user clearing is
          // reason "clear". So only this exact case is the sentinel reset.
          if (reason === "reset" && v === "") return;
          setDraft(v);
          onChange(v);
        }}
        onChange={(_, v) => {
          // Selecting the sentinel opens the dialog; it must NOT set the model.
          if (v != null && typeof v !== "string" && isAddCustom(v)) {
            setEndpointOpen(true);
            return;
          }
          const id = v == null ? "" : typeof v === "string" ? v : v.id;
          setDraft(id);
          onChange(id);
        }}
        renderInput={(params) => (
          <TextField
            {...params}
            label={label}
            size="small"
            placeholder="provider/model — e.g. openrouter/moonshotai/kimi-k2 or kimi/kimi-k2.6"
            helperText="Type provider/model. Pick from configured providers or type a custom endpoint id; use ‘Add API key’ if it shows ‘no key’."
          />
        )}
      />
      {modelProvider && (
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
          <Button size="small" variant="outlined" startIcon={<VpnKeyIcon />}
                  onClick={() => setDlgOpen(true)}>
            {isolated ? "Set your session key" : "Set API key"} ({modelProvider})
          </Button>
          <Typography variant="caption" color="text.secondary">
            {isolated
              ? "kept in your session only — not shared with other users of this UI"
              : "stored in opencode auth.json — auto-used for runs (no export needed)"}
          </Typography>
        </Stack>
      )}
      {result && (
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
          {result.status === "ok" && (
            <Chip size="small" color="success" icon={<CheckCircleIcon />} label="available" />
          )}
          {result.status === "model_not_found" && (
            <Chip size="small" color="warning" icon={<WarningAmberIcon />} label="not in catalog" />
          )}
          {result.status === "unverified" && (
            <Chip size="small" variant="outlined" color="info"
                  icon={<HelpOutlineIcon />} label="couldn't verify" />
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
      {(result?.status === "unverified" || result?.status === "model_not_found") && (
        <Typography variant="caption" color="text.secondary">
          Advisory only — this doesn't block running. Pick a suggestion or run as-is
          if the id is correct for your endpoint.
        </Typography>
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
        provider={modelProvider || result?.provider || ""}
        onClose={() => setDlgOpen(false)}
        onSaved={() => {
          // Retrigger validation after saving the key.
          mut.mutateAsync(draft).then(setResult).catch(() => {});
        }}
      />
      <CustomEndpointDialog
        open={endpointOpen}
        onClose={() => setEndpointOpen(false)}
        onAdd={(input) => {
          setEndpointOpen(false);
          // Parent merges the endpoint + remounts the form (this widget then
          // unmounts) — the synchronous callback has already fired by then.
          onAddCustomEndpoint?.(input);
        }}
      />
    </Stack>
  );
}
