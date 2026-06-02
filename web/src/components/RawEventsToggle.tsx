import { useState } from "react";
import { Box, Button, Typography } from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";

interface Props { events: unknown[]; }

export default function RawEventsToggle({ events }: Props) {
  const [open, setOpen] = useState(false);
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
        {open ? "hide raw" : "show raw"}
      </Button>
      {open && (
        <Box sx={{
          mt: 1, p: 1, bgcolor: "#0e1116", color: "#dbe1ec",
          fontFamily: "monospace", fontSize: 12, borderRadius: 1,
          maxHeight: 320, overflow: "auto", userSelect: "text",
        }}>
          {events.map((e, i) => (
            <Typography key={i} variant="caption" component="div">
              {JSON.stringify(e)}
            </Typography>
          ))}
        </Box>
      )}
    </Box>
  );
}
