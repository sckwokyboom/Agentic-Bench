import { useState } from "react";
import {
  Box, Button, Typography, CircularProgress, Link, Stack,
  ToggleButton, ToggleButtonGroup,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { useRunLog, logUrl, type LogKind } from "../api/queries";

interface Props {
  name: string;
  condition: string;
  rep: number;
  batch?: string;
}

// Collapsible dark-terminal viewer for the per-run log. Two views: "readable"
// (run.log — stages, tool/llm one-liners, results, errors; the default) and
// "full" (debug.log — readable lines + opencode's verbose stderr). Lazy-fetched
// (only once expanded) and capped to the tail so a multi-MB log can't freeze the
// browser; the full file is one click away via "Download full log".
export default function RunLogToggle({ name, condition, rep, batch }: Props) {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<LogKind>("readable");
  const log = useRunLog(name, condition, rep, open, batch, kind);
  return (
    <Box>
      <Button
        size="small"
        onClick={() => setOpen(!open)}
        endIcon={
          <ExpandMoreIcon
            sx={{ transform: open ? "rotate(180deg)" : "none", transition: "transform 0.2s" }}
          />
        }
      >
        {open ? "hide run log" : "show run log"}
      </Button>
      {open && (
        <Box sx={{
          mt: 1, p: 1.5, bgcolor: "#0e1116", color: "#dbe1ec",
          fontFamily: "monospace", fontSize: 12, borderRadius: 1,
          maxHeight: 480, overflow: "auto", userSelect: "text",
        }}>
          <Stack
            direction="row"
            alignItems="center"
            justifyContent="space-between"
            sx={{ mb: 1 }}
          >
            <ToggleButtonGroup
              size="small"
              exclusive
              value={kind}
              onChange={(_e, v: LogKind | null) => v && setKind(v)}
              sx={{
                "& .MuiToggleButton-root": {
                  color: "#9aa4b2", borderColor: "#2a3340", py: 0.1, px: 1,
                  fontSize: 11, textTransform: "none",
                },
                "& .Mui-selected": { color: "#dbe1ec !important", bgcolor: "#1b2330 !important" },
              }}
            >
              <ToggleButton value="readable">readable</ToggleButton>
              <ToggleButton value="full">full (debug)</ToggleButton>
            </ToggleButtonGroup>
            <Link
              href={logUrl(name, condition, rep, kind, batch)}
              target="_blank"
              rel="noopener"
              variant="caption"
              sx={{ color: "#8ab4ff" }}
            >
              Download full log
            </Link>
          </Stack>
          {log.isLoading && <CircularProgress size={16} sx={{ color: "#dbe1ec" }} />}
          {log.error && (
            <Typography variant="caption" component="div" sx={{ color: "inherit" }}>
              {kind === "full"
                ? "No full (debug) log for this run."
                : "No run log for this run."}
            </Typography>
          )}
          {log.data != null && (
            // Only the tail is fetched (see useRunLog) so a multi-MB log can't
            // freeze the browser; the link above has the full file.
            <Box component="pre" sx={{ m: 0, whiteSpace: "pre-wrap" }}>{log.data}</Box>
          )}
        </Box>
      )}
    </Box>
  );
}
