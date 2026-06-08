import { useState } from "react";
import {
  Button, Menu, MenuItem, ListItemText, Snackbar, Tooltip,
} from "@mui/material";
import DownloadIcon from "@mui/icons-material/Download";
import ArrowDropDownIcon from "@mui/icons-material/ArrowDropDown";
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
 * a batch, as either the FULL artifact or a COMPACT DIGEST (diff bodies → +/-
 * counts, text truncated) that's small enough to paste into a chat. The server
 * applies the allowlist + scrubbing (ids/URLs/secrets/usernames stripped, raw
 * tool outputs excluded) — see abench.safe_trace. Always review before sharing.
 */
export default function SafeTraceButton({ name, condition, rep, batch, label }: Props) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const [busy, setBusy] = useState(false);
  const [snack, setSnack] = useState<string | null>(null);
  const single = condition != null && rep != null;

  async function run(digest: boolean): Promise<void> {
    setAnchor(null);
    setBusy(true);
    try {
      const qs = new URLSearchParams();
      if (batch) qs.set("batch", batch);
      if (digest) qs.set("digest", "true");
      const q = qs.toString();
      const path = single
        ? `/api/runs/${encodeURIComponent(name)}/${encodeURIComponent(condition!)}/${rep}/safe_trace`
        : `/api/runs/${encodeURIComponent(name)}/safe_traces`;
      const bundle = await apiGet<Bundle>(`${path}${q ? `?${q}` : ""}`);
      const kind = digest ? "digest" : "trace";
      const slug = (single ? `${name}-${condition}-rep${rep}` : `${name}${batch ? `-${batch}` : ""}`)
        .replace(/[^\w.-]+/g, "_");
      downloadText(`safe-${kind}-${slug}.json`, JSON.stringify(bundle, null, 2));
      const redactions = Object.values(bundle.redaction ?? {}).reduce((a, b) => a + b, 0);
      setSnack(`Downloaded ${bundle.n_traces} redacted ${kind}(s) · ${redactions} redactions — review before sharing.`);
    } catch (e) {
      setSnack(`Safe-trace export failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Tooltip title="Download a redacted, share-safe copy (ids / URLs / secrets / usernames stripped; raw tool outputs excluded). Digest = compact, pasteable. Review before sharing.">
        <span>
          <Button
            size="small"
            variant="outlined"
            startIcon={<DownloadIcon />}
            endIcon={<ArrowDropDownIcon />}
            disabled={busy}
            aria-label="download safe trace"
            onClick={(e) => setAnchor(e.currentTarget)}
            sx={{ minWidth: 150 }}
          >
            {busy ? "Exporting…" : (label ?? "Safe trace")}
          </Button>
        </span>
      </Tooltip>
      <Menu anchorEl={anchor} open={Boolean(anchor)} onClose={() => setAnchor(null)}>
        <MenuItem onClick={() => run(true)}>
          <ListItemText
            primary="Compact digest (for pasting)"
            secondary="diff bodies → +/- counts, text truncated"
          />
        </MenuItem>
        <MenuItem onClick={() => run(false)}>
          <ListItemText primary="Full safe trace" secondary="complete, for review / archive" />
        </MenuItem>
      </Menu>
      <Snackbar
        open={Boolean(snack)}
        autoHideDuration={6000}
        onClose={() => setSnack(null)}
        message={snack ?? ""}
      />
    </>
  );
}
