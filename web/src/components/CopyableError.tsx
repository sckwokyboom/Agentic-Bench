import { useState } from "react";
import { Alert, Box, IconButton, Tooltip } from "@mui/material";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import CheckIcon from "@mui/icons-material/Check";
import { selectable } from "../theme";
import { copyText } from "../lib/clipboard";

interface Props {
  message: string;
  severity?: "error" | "warning" | "info" | "success";
  sx?: object;
}

/**
 * An error banner whose text is SELECTABLE and has a one-click copy button, so
 * long backend errors (sandbox build failures, provider/auth errors, stack
 * traces) can be lifted out as plain text and pasted elsewhere. The app sets a
 * global `body { user-select: none }` (theme.tsx) to keep chrome from looking
 * editable, so error text must opt back in — without this you can't even
 * highlight the message to copy it by hand.
 */
export default function CopyableError({ message, severity = "error", sx }: Props) {
  const [copied, setCopied] = useState(false);
  async function onCopy() {
    if (await copyText(message)) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  }
  return (
    <Alert
      severity={severity}
      sx={sx}
      action={
        <Tooltip title={copied ? "Copied" : "Copy"}>
          <IconButton
            aria-label="copy error message"
            size="small"
            color="inherit"
            onClick={onCopy}
          >
            {copied ? <CheckIcon fontSize="inherit" /> : <ContentCopyIcon fontSize="inherit" />}
          </IconButton>
        </Tooltip>
      }
    >
      <Box component="span" sx={{ ...selectable, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
        {message}
      </Box>
    </Alert>
  );
}
