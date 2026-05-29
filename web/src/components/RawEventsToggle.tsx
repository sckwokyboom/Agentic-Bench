import { useState } from "react";
import { Box, Button, Typography } from "@mui/material";

interface Props { events: unknown[]; }

export default function RawEventsToggle({ events }: Props) {
  const [open, setOpen] = useState(false);
  return (
    <Box>
      <Button size="small" onClick={() => setOpen(!open)}>
        {open ? "hide raw ▴" : "show raw ▾"}
      </Button>
      {open && (
        <Box sx={{
          mt: 1, p: 1, bgcolor: "#0e1116", color: "#dbe1ec",
          fontFamily: "monospace", fontSize: 12, borderRadius: 1,
          maxHeight: 320, overflow: "auto",
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
