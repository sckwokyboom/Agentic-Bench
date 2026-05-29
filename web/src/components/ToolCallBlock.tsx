import { Box, Typography } from "@mui/material";

interface Props { call: any; result?: any; }

export default function ToolCallBlock({ call, result }: Props) {
  const ok = result ? !result.is_error : null;
  const icon = result ? (ok ? "✓" : "✗") : "✎";
  const name = call?.name ?? "?";
  const summary = JSON.stringify(call?.input ?? {}).slice(0, 200);
  const outputSnippet = result ? String(result.output ?? "").slice(0, 200) : null;
  return (
    <Box sx={{ pl: 1, borderLeft: 2, borderLeftColor: ok === false ? "error.main" : "primary.light", my: 1 }}>
      <Typography variant="body2"><b>{icon} {name}</b> {summary}</Typography>
      {outputSnippet && (
        <Typography variant="caption" color="text.secondary" sx={{ whiteSpace: "pre-wrap" }}>
          → {outputSnippet}
        </Typography>
      )}
    </Box>
  );
}
