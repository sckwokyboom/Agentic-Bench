import { useState } from "react";
import {
  Card, CardContent, Stack, Typography, Button, Box, Alert, AlertTitle,
} from "@mui/material";
import { usePatch } from "../api/queries";
import { parsePatch, type PatchFile } from "../lib/parsePatch";

interface Props {
  name: string;
  condition: string;
  rep: number;
  batch?: string;
  // Explicit signal from metrics (`made_source_changes`). When false we warn
  // rather than show an empty card, even if a (non-source) patch slipped in.
  // Undefined → fall back to "is the patch empty?".
  madeSourceChanges?: boolean;
}

function HunkLine({ line }: { line: string }) {
  let color = "text.primary";
  let bg = "transparent";
  if (line.startsWith("+") && !line.startsWith("+++")) { color = "success.main"; bg = "rgba(46,125,50,0.08)"; }
  else if (line.startsWith("-") && !line.startsWith("---")) { color = "error.main"; bg = "rgba(211,47,47,0.08)"; }
  else if (line.startsWith("@@")) { color = "text.secondary"; }
  return (
    <Box sx={{ color, bgcolor: bg, fontFamily: "monospace", fontSize: 12, whiteSpace: "pre", userSelect: "text" }}>
      {line || " "}
    </Box>
  );
}

export default function FinalDiffCard({
  name, condition, rep, batch, madeSourceChanges,
}: Props) {
  const patch = usePatch(name, condition, rep, batch);
  const batchQs = batch ? `?batch=${encodeURIComponent(batch)}` : "";
  const [expanded, setExpanded] = useState(false);
  if (patch.isLoading) return null;
  // No source changes when metrics say so explicitly, or (lacking that signal)
  // when the patch is empty. Surface a prominent warning so a silent 42/42 on
  // an untouched project is impossible to miss.
  const noChanges = madeSourceChanges === false || !patch.data || patch.data.length === 0;
  if (noChanges) {
    return (
      <Alert severity="warning">
        <AlertTitle>No source changes</AlertTitle>
        The agent did not edit any files. Verify results below reflect the
        unmodified project.
      </Alert>
    );
  }
  const files: PatchFile[] = parsePatch(patch.data);
  const totalAdded = files.reduce((s, f) => s + f.added, 0);
  const totalRemoved = files.reduce((s, f) => s + f.removed, 0);
  // Spec §7.4: only diffs with ≥5 files or ≥200 lines collapse to the first 3.
  // Invariant: files are hidden ⟺ a "show all" toggle exists (guard on !isLong
  // so a short 4-file diff renders all 4 instead of silently dropping #4).
  const isLong = files.length >= 5 || (totalAdded + totalRemoved) >= 200;
  const showFiles = expanded || !isLong ? files : files.slice(0, 3);

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack direction="row" alignItems="center" spacing={1}>
          <Typography variant="subtitle2">
            Final diff — {files.length} file{files.length === 1 ? "" : "s"}, +{totalAdded}/−{totalRemoved}
          </Typography>
          <Box sx={{ flex: 1 }} />
          <Button
            size="small"
            href={`/api/runs/${name}/${condition}/${rep}/patch${batchQs}`}
            download={`changes-${condition}-${rep}.patch`}
          >Download .patch</Button>
        </Stack>
        <Stack spacing={1} sx={{ mt: 1 }}>
          {showFiles.map((f) => (
            <Box key={f.path}>
              <Typography variant="body2"><b>{f.path}</b> · +{f.added}/−{f.removed}</Typography>
              <Box sx={{ borderLeft: 2, borderLeftColor: "divider", pl: 1, mt: 0.5 }}>
                {f.hunkLines.map((ln, i) => <HunkLine key={i} line={ln} />)}
              </Box>
            </Box>
          ))}
        </Stack>
        {isLong && !expanded && (
          <Button size="small" onClick={() => setExpanded(true)} sx={{ mt: 1 }}>
            show all {files.length} files
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
