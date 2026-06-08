import { useState } from "react";
import { Button, Snackbar, Tooltip } from "@mui/material";
import DownloadIcon from "@mui/icons-material/Download";
import { apiGet } from "../api/client";
import { downloadText } from "../lib/download";

interface Props {
  name: string;
  condition?: string;   // omit (with rep) → batch-wide bundle of every run
  rep?: number;
  batch?: string | null;
  label?: string;
}

interface Bundle {
  n_traces: number;
  redaction?: Record<string, number>;
}

/**
 * Download a REDACTED, share-safe copy of a run's trace (per-run) or every run in
 * a batch. The server applies the allowlist + scrubbing (ids/URLs/secrets/
 * usernames stripped, raw tool outputs excluded) — see abench.safe_trace. The
 * snackbar reports the redaction count; always review the file before sharing.
 */
export default function SafeTraceButton({ name, condition, rep, batch, label }: Props) {
  const [busy, setBusy] = useState(false);
  const [snack, setSnack] = useState<string | null>(null);
  const single = condition != null && rep != null;

  async function run(): Promise<void> {
    setBusy(true);
    try {
      const qs = new URLSearchParams();
      if (batch) qs.set("batch", batch);
      const q = qs.toString();
      const path = single
        ? `/api/runs/${encodeURIComponent(name)}/${encodeURIComponent(condition!)}/${rep}/safe_trace`
        : `/api/runs/${encodeURIComponent(name)}/safe_traces`;
      const bundle = await apiGet<Bundle>(`${path}${q ? `?${q}` : ""}`);
      const slug = (single ? `${name}-${condition}-rep${rep}` : `${name}${batch ? `-${batch}` : ""}`)
        .replace(/[^\w.-]+/g, "_");
      downloadText(`safe-trace-${slug}.json`, JSON.stringify(bundle, null, 2));
      const redactions = Object.values(bundle.redaction ?? {}).reduce((a, b) => a + b, 0);
      setSnack(`Downloaded ${bundle.n_traces} redacted trace(s) · ${redactions} redactions — review before sharing.`);
    } catch (e) {
      setSnack(`Safe-trace export failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Tooltip title="Download a redacted, share-safe copy (ids / URLs / secrets / usernames stripped; raw tool outputs excluded). Review before sharing.">
        <span>
          <Button
            size="small"
            variant="outlined"
            startIcon={<DownloadIcon />}
            disabled={busy}
            aria-label="download safe trace"
            onClick={run}
            sx={{ minWidth: 150 }}
          >
            {busy ? "Exporting…" : (label ?? "Safe trace")}
          </Button>
        </span>
      </Tooltip>
      <Snackbar
        open={Boolean(snack)}
        autoHideDuration={6000}
        onClose={() => setSnack(null)}
        message={snack ?? ""}
      />
    </>
  );
}
