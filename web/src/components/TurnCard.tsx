import { useState, type ReactNode } from "react";
import { Card, CardContent, Stack, Typography, Chip, Box, Button, Tooltip } from "@mui/material";
import PsychologyOutlinedIcon from "@mui/icons-material/PsychologyOutlined";
import ChatBubbleOutlineIcon from "@mui/icons-material/ChatBubbleOutline";
import EditNoteIcon from "@mui/icons-material/EditNote";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import CancelIcon from "@mui/icons-material/Cancel";
import PendingOutlinedIcon from "@mui/icons-material/PendingOutlined";
import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import RawEventsToggle from "./RawEventsToggle";
import { formatTokens } from "../lib/formatTokens";
import { selectable } from "../theme";
import { toolBreakdown, turnObsTokens, formatToolArgs, type UiPart, type UiTurn } from "../lib/traceModel";

interface Props { turn: UiTurn; index: number; rawEvents: unknown[]; }

const COLLAPSE = 600;

// Inline glyph rendered before a Typography's text: inherits the font size and
// sits on the text baseline so it reads as a leading marker, not a standalone icon.
const inlineIcon = { fontSize: "inherit", verticalAlign: "middle", mr: 0.5 } as const;

// Expandable block: full text is always reachable (collapsed only past COLLAPSE,
// never hard-truncated), so a trace stays fully inspectable.
function Expand({ text, render }: { text: string; render: (shown: string) => ReactNode }) {
  const [open, setOpen] = useState(false);
  const long = text.length > COLLAPSE;
  const shown = open || !long ? text : text.slice(0, COLLAPSE) + "…";
  return (
    <>
      {render(shown)}
      {long && (
        <Button size="small" onClick={() => setOpen(!open)} sx={{ mt: 0.25, py: 0, minWidth: 0 }}>
          {open ? "show less" : `show more (${text.length.toLocaleString()} chars)`}
        </Button>
      )}
    </>
  );
}

function Long({ text, prefix, accent }: { text: string; prefix: ReactNode; accent: string }) {
  return (
    <Box sx={{ borderLeft: 2, borderColor: accent, pl: 1.5, py: 0.25 }}>
      <Expand text={text} render={(shown) => (
        <Typography variant="body2" sx={{ whiteSpace: "pre-wrap", ...selectable }}>{prefix}{shown}</Typography>
      )} />
    </Box>
  );
}

// Full file diff, expandable (was hard-truncated at 400 chars before — that hid
// the bulk of the agent's actual change).
function EditPart({ path, patch }: { path: string; patch: string }) {
  return (
    <Box sx={{ borderLeft: 2, borderColor: "warning.main", pl: 1.5 }}>
      <Typography variant="body2" sx={selectable}>
        <b><EditNoteIcon color="warning" sx={inlineIcon} />{path}</b>
      </Typography>
      <Expand text={patch} render={(shown) => (
        <Typography variant="caption" component="pre" sx={{ m: 0, whiteSpace: "pre-wrap", ...selectable }}>{shown}</Typography>
      )} />
    </Box>
  );
}

// A deterministic controller action (ran suite / accepted / reverted). Accent by
// the gate decision so accept (green) / revert (red) pop; full text expandable.
function ControllerPart({ text }: { text: string }) {
  const accent = /revert/i.test(text) ? "error.main"
    : /(accept|green)/i.test(text) ? "success.main" : "info.main";
  return (
    <Box sx={{ borderLeft: 2, borderColor: accent, pl: 1.5, py: 0.25 }}>
      <Expand text={text} render={(shown) => (
        <Typography variant="body2" sx={{ whiteSpace: "pre-wrap", fontFamily: "monospace", fontSize: 13, ...selectable }}>
          <SettingsOutlinedIcon sx={{ ...inlineIcon, color: accent }} />{shown}
        </Typography>
      )} />
    </Box>
  );
}

function ToolPart({ p }: { p: Extract<UiPart, { kind: "tool" }> }) {
  return (
    <Box sx={{ borderLeft: 2, borderColor: p.ok === false ? "error.main" : "success.main", pl: 1.5, ...selectable }}>
      <Typography variant="body2">
        <b>
          {p.ok === false
            ? <CancelIcon color="error" sx={inlineIcon} />
            : p.ok
              ? <CheckCircleIcon color="success" sx={inlineIcon} />
              : <PendingOutlinedIcon color="disabled" sx={inlineIcon} />}
          {p.name}
        </b> {formatToolArgs(p.name, p.args)}
        {p.exitCode != null && p.exitCode !== 0 && <> · exit {p.exitCode}</>}
        {p.outputTokens > 0 && (
          <Typography component="span" variant="caption" color="text.secondary">
            {" · ≈"}{formatTokens(p.outputTokens)} tok ctx
          </Typography>
        )}
      </Typography>
      {p.output && (
        <Expand text={p.output} render={(shown) => (
          <Typography variant="caption" color="text.secondary" component="div"
            sx={{ whiteSpace: "pre-wrap", ...selectable }}>→ {shown}</Typography>
        )} />
      )}
    </Box>
  );
}

export default function TurnCard({ turn, index, rawEvents }: Props) {
  const breakdown = toolBreakdown(turn);
  const breakdownStr = Object.entries(breakdown).map(([n, c]) => `${n} ×${c}`).join(" · ") || "no tools";
  return (
    <Card variant="outlined">
      <CardContent>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }} flexWrap="wrap">
          {turn.isController
            ? <Tooltip arrow title="Orchestrator action — a deterministic step the controller ran (baseline suite, accept/revert a round, finalize). NOT an LLM turn, so no tokens.">
                <Chip size="small" color="info" variant="outlined" icon={<SettingsOutlinedIcon />} label="controller" />
              </Tooltip>
            : <Chip size="small" variant="outlined" label={`turn ${index + 1}`} />}
          {turn.reason && (
            <Tooltip arrow title="The AGENT's turn-end reason (why the model ended this turn): tool-calls = paused to call tools, will continue; stop = ended its turn; length = hit the token limit.">
              <Chip size="small" color="primary" label={turn.reason} />
            </Tooltip>
          )}
          {turn.phase && (
            <Tooltip arrow title="Orchestration PHASE the controller put the agent in (understand → plan → implement → diagnose). Shown on both the agent's turns and the controller's actions inside that phase.">
              <Chip size="small" variant="outlined" label={`phase: ${turn.phase}`} sx={{ textTransform: "none" }} />
            </Tooltip>
          )}
          <Box sx={{ flexGrow: 1 }} />
          {!turn.isController && (
            <Tooltip
              arrow
              title={
                "Per-turn (not cumulative). in = the FULL input context sent to "
                + "the model this turn — it re-includes all prior turns, so it grows "
                + "turn over turn. out = tokens generated this turn. obs = est. "
                + "tokens of this turn's tool outputs (which become part of the next "
                + "turn's input)."
              }
            >
              <Typography variant="caption" color="text.secondary"
                sx={{ borderBottom: "1px dotted", borderColor: "divider", cursor: "help" }}>
                in {formatTokens(turn.tokensIn)} · out {formatTokens(turn.tokensOut)}
                {turnObsTokens(turn) > 0 && <> · obs ≈{formatTokens(turnObsTokens(turn))}</>}
                {turn.cost != null && <> · ${turn.cost.toFixed(4)}</>}
                {turn.durationS != null && <> · {turn.durationS.toFixed(1)}s</>}
              </Typography>
            </Tooltip>
          )}
        </Stack>

        <Stack spacing={1.25}>
          {turn.parts.map((p, i) => {
            if (p.kind === "reasoning") return <Long key={i} prefix={<PsychologyOutlinedIcon color="info" sx={inlineIcon} />} accent="info.main" text={p.text} />;
            if (p.kind === "text") return <Long key={i} prefix={<ChatBubbleOutlineIcon sx={{ ...inlineIcon, color: "text.primary" }} />} accent="text.primary" text={p.text} />;
            if (p.kind === "edit") return <EditPart key={i} path={p.path} patch={p.patch} />;
            if (p.kind === "controller") return <ControllerPart key={i} text={p.text} />;
            if (p.kind === "tool") return <ToolPart key={i} p={p} />;
            return null;
          })}
        </Stack>

        {!turn.isController && (
          <>
            <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1.5 }}>
              {breakdownStr}
            </Typography>
            <RawEventsToggle events={rawEvents} />
          </>
        )}
      </CardContent>
    </Card>
  );
}
