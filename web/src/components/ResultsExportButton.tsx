import { useState } from "react";
import {
  Button, Menu, MenuItem, Snackbar, ListItemIcon, ListItemText, Divider,
} from "@mui/material";
import IosShareIcon from "@mui/icons-material/IosShare";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import DownloadIcon from "@mui/icons-material/Download";
import type { RunsSummary, RunSummary } from "../api/types";
import { buildResultsMarkdown, buildRunsCsv } from "../lib/exportTable";
import { downloadText } from "../lib/download";

interface Props {
  experimentName: string;
  batchLabel?: string | null;
  summary: RunsSummary | null | undefined;
  runs: RunSummary[] | null | undefined;
}

/**
 * Export the results tables as text — Markdown (paste into an LLM or a team
 * chat) or CSV (spreadsheets) — via clipboard copy or file download. Copy needs
 * a secure context (https/localhost); if it's blocked, download always works.
 */
export default function ResultsExportButton({
  experimentName, batchLabel, summary, runs,
}: Props) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const [snack, setSnack] = useState<string | null>(null);
  const close = () => setAnchor(null);

  const hasData =
    (summary?.conditions.length ?? 0) > 0 || (runs?.length ?? 0) > 0;
  const meta = { experimentName, batchLabel };
  const slug = `${experimentName}${batchLabel ? `-${batchLabel}` : ""}`
    .replace(/[^\w.-]+/g, "_");

  async function copy(text: string, what: string): Promise<void> {
    close();
    try {
      await navigator.clipboard.writeText(text);
      setSnack(`${what} copied to clipboard`);
    } catch {
      setSnack("Clipboard blocked here — use Download instead");
    }
  }

  return (
    <>
      <Button
        size="small"
        variant="outlined"
        startIcon={<IosShareIcon />}
        disabled={!hasData}
        aria-label="export results"
        onClick={(e) => setAnchor(e.currentTarget)}
        sx={{ minWidth: 150 }}
      >
        Export
      </Button>
      <Menu anchorEl={anchor} open={Boolean(anchor)} onClose={close}>
        <MenuItem onClick={() => copy(buildResultsMarkdown(meta, summary, runs), "Markdown")}>
          <ListItemIcon><ContentCopyIcon fontSize="small" /></ListItemIcon>
          <ListItemText>Copy as Markdown</ListItemText>
        </MenuItem>
        <MenuItem onClick={() => copy(buildRunsCsv(runs), "CSV")}>
          <ListItemIcon><ContentCopyIcon fontSize="small" /></ListItemIcon>
          <ListItemText>Copy runs as CSV</ListItemText>
        </MenuItem>
        <Divider />
        <MenuItem
          onClick={() => {
            close();
            downloadText(`${slug}.md`, buildResultsMarkdown(meta, summary, runs), "text/markdown");
          }}
        >
          <ListItemIcon><DownloadIcon fontSize="small" /></ListItemIcon>
          <ListItemText>Download .md</ListItemText>
        </MenuItem>
        <MenuItem
          onClick={() => {
            close();
            downloadText(`${slug}.csv`, buildRunsCsv(runs), "text/csv");
          }}
        >
          <ListItemIcon><DownloadIcon fontSize="small" /></ListItemIcon>
          <ListItemText>Download runs .csv</ListItemText>
        </MenuItem>
      </Menu>
      <Snackbar
        open={Boolean(snack)}
        autoHideDuration={3000}
        onClose={() => setSnack(null)}
        message={snack ?? ""}
      />
    </>
  );
}
