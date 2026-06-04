import { useState } from "react";
import { Box, Button, Typography, CircularProgress, Link, Stack } from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { useRunLog, runLogUrl } from "../api/queries";

interface Props {
  name: string;
  condition: string;
  rep: number;
  batch?: string;
}

// Collapsible dark-terminal viewer for the raw agent run log (run.log), reusing
// the RawEventsToggle styling. The text is lazy-fetched: the query is enabled
// only once expanded, so we don't pull a potentially large log eagerly. A 404
// (no log written for this run) degrades to a friendly message.
export default function RunLogToggle({ name, condition, rep, batch }: Props) {
  const [open, setOpen] = useState(false);
  const log = useRunLog(name, condition, rep, open, batch);
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
          {log.isLoading && <CircularProgress size={16} sx={{ color: "#dbe1ec" }} />}
          {log.error && (
            <Typography variant="caption" component="div" sx={{ color: "inherit" }}>
              No run log for this run.
            </Typography>
          )}
          {log.data != null && (
            <Stack spacing={1}>
              <Link
                href={runLogUrl(name, condition, rep, batch)}
                target="_blank"
                rel="noopener"
                variant="caption"
                sx={{ color: "#8ab4ff", alignSelf: "flex-start" }}
              >
                Download full log
              </Link>
              {/* Only the tail is fetched (see useRunLog) so a multi-MB build
                  log can't freeze the browser; the link above has the full log. */}
              <Box component="pre" sx={{ m: 0, whiteSpace: "pre-wrap" }}>{log.data}</Box>
            </Stack>
          )}
        </Box>
      )}
    </Box>
  );
}
