import { useState } from "react";
import { Card, CardContent, Stack, Typography, Button, Box } from "@mui/material";
import { usePatch } from "../api/queries";
import { parsePatch, type PatchFile } from "../lib/parsePatch";

interface Props {
  name: string;
  condition: string;
  rep: number;
}

function HunkLine({ line }: { line: string }) {
  let color = "text.primary";
  let bg = "transparent";
  if (line.startsWith("+") && !line.startsWith("+++")) { color = "success.main"; bg = "rgba(46,125,50,0.08)"; }
  else if (line.startsWith("-") && !line.startsWith("---")) { color = "error.main"; bg = "rgba(211,47,47,0.08)"; }
  else if (line.startsWith("@@")) { color = "text.secondary"; }
  return (
    <Box sx={{ color, bgcolor: bg, fontFamily: "monospace", fontSize: 12, whiteSpace: "pre" }}>
      {line || " "}
    </Box>
  );
}

export default function FinalDiffCard({ name, condition, rep }: Props) {
  const patch = usePatch(name, condition, rep);
  const [expanded, setExpanded] = useState(false);
  if (patch.isLoading) return null;
  if (!patch.data || patch.data.length === 0) {
    return (
      <Card variant="outlined">
        <CardContent>
          <Typography variant="subtitle2">Final diff — no changes</Typography>
        </CardContent>
      </Card>
    );
  }
  const files: PatchFile[] = parsePatch(patch.data);
  const totalAdded = files.reduce((s, f) => s + f.added, 0);
  const totalRemoved = files.reduce((s, f) => s + f.removed, 0);
  const showFiles = expanded ? files : files.slice(0, 3);
  const isLong = files.length >= 5 || (totalAdded + totalRemoved) >= 200;

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
            href={`/api/runs/${name}/${condition}/${rep}/patch`}
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
