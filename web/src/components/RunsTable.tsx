import {
  Table, TableHead, TableBody, TableRow, TableCell, Typography, Box, Tooltip, Stack,
  CircularProgress, Checkbox,
} from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import CancelIcon from "@mui/icons-material/Cancel";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline";
import GavelIcon from "@mui/icons-material/Gavel";
import EditOffIcon from "@mui/icons-material/EditOff";
import LoopIcon from "@mui/icons-material/Loop";
import VerifyStatusChip from "./VerifyStatusChip";
import { CHEATING_LABELS } from "./ValiditySignals";
import { selectable } from "../theme";
import type { RunSummary, VerifyStatus } from "../api/types";

// Live re-verify progress for the visible runs. Presence of this prop means a
// re-verify job is in flight; each row then shows queued → verifying → its fresh
// verdict, instead of the (stale) stored status.
export interface ReverifyProgress {
  current: { condition: string; rep: number } | null;
  resultByKey: Record<string, VerifyStatus | null>; // "condition/rep" → new status
}

interface Props {
  rows: RunSummary[];
  onOpen: (condition: string, rep: number) => void;
  reverify?: ReverifyProgress;
  // When both are provided, a leading checkbox column lets a run be included/
  // excluded from the comparison aggregates above. `excluded` holds "condition/
  // rep" keys; unticking calls onToggleRun (which recomputes the panel). The row
  // stays clickable — clicking anywhere but the checkbox still opens the trace.
  excluded?: ReadonlySet<string>;
  onToggleRun?: (key: string) => void;
}

function num(v: number | null | undefined, digits = 0): string {
  return v == null ? "—" : v.toFixed(digits);
}

// The verify cell. While a re-verify is in flight (`reverify` present): the
// running row shows a spinner, finished rows show their fresh verdict, and the
// rest show "queued". Otherwise the stored verify status.
function VerifyCell({ row, reverify }: { row: RunSummary; reverify?: ReverifyProgress }) {
  if (reverify) {
    const c = reverify.current;
    if (c && c.condition === row.condition && c.rep === row.rep) {
      return (
        <Stack direction="row" alignItems="center" spacing={0.5}>
          <CircularProgress size={14} />
          <Typography variant="caption" color="text.secondary">verifying…</Typography>
        </Stack>
      );
    }
    const key = `${row.condition}/${row.rep}`;
    if (key in reverify.resultByKey) {
      return <VerifyStatusChip status={reverify.resultByKey[key] ?? null} />;
    }
    return <Typography variant="caption" color="text.secondary">queued</Typography>;
  }
  return <VerifyStatusChip status={row.verify_status} />;
}

export default function RunsTable({ rows, onOpen, reverify, excluded, onToggleRun }: Props) {
  if (rows.length === 0) {
    return <Typography variant="body2" color="text.secondary">No runs yet.</Typography>;
  }
  const selectMode = Boolean(onToggleRun);
  return (
    <Box sx={{ border: 1, borderColor: "divider", borderRadius: 1 }}>
      <Table size="small">
        <TableHead>
          <TableRow>
            {selectMode && <TableCell padding="checkbox" />}
            <TableCell>condition</TableCell>
            <TableCell align="right">rep</TableCell>
            <TableCell>verify</TableCell>
            <TableCell>success</TableCell>
            <TableCell align="right">duration (s)</TableCell>
            <TableCell align="right">steps</TableCell>
            <TableCell align="right">tools</TableCell>
            <TableCell align="right">tests</TableCell>
            <TableCell align="right">cost ($)</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((r) => {
            const isVerifying = !!(
              reverify?.current &&
              reverify.current.condition === r.condition &&
              reverify.current.rep === r.rep
            );
            const key = `${r.condition}/${r.rep}`;
            const isExcluded = selectMode && (excluded?.has(key) ?? false);
            return (
            <TableRow
              key={`${r.condition}-${r.rep}`}
              hover
              selected={isVerifying}
              onClick={() => onOpen(r.condition, r.rep)}
              sx={{
                cursor: "pointer",
                ...(isExcluded && {
                  "& > td:not(.selcol)": { opacity: 0.4, textDecoration: "line-through" },
                }),
              }}
            >
              {selectMode && (
                <TableCell padding="checkbox" className="selcol" onClick={(e) => e.stopPropagation()}>
                  <Checkbox
                    size="small"
                    checked={!isExcluded}
                    onChange={() => onToggleRun!(key)}
                    inputProps={{ "aria-label": `include ${key}` }}
                  />
                </TableCell>
              )}
              <TableCell>
                <Stack direction="row" alignItems="center" spacing={0.5}>
                  <span>{r.condition}</span>
                  {(r.n_service_errors ?? 0) > 0 && (
                    <Tooltip title={`${r.n_service_errors} service/proxy error${r.n_service_errors === 1 ? "" : "s"} during this run`}>
                      <ErrorOutlineIcon color="error" fontSize="small" />
                    </Tooltip>
                  )}
                  {r.cheating?.verdict === "suspicious" && (
                    <Tooltip title={"Possible cheating: " + r.cheating.signals
                      .map((s) => CHEATING_LABELS[s.type] ?? s.type).join("; ")}>
                      <GavelIcon color="warning" fontSize="small" />
                    </Tooltip>
                  )}
                  {r.made_source_changes === false && (
                    <Tooltip title={
                      "Agent made NO source edits — likely didn't attempt/finish the task"
                      + (r.stop_reason ? ` (model ended: ${r.stop_reason})` : "")
                    }>
                      <EditOffIcon color="warning" fontSize="small" />
                    </Tooltip>
                  )}
                  {(r.stuck || r.interrupted_reason === "looping") && (
                    <Tooltip title="Stopped by the loop watchdog — agent repeated the same step with no progress (stuck)">
                      <LoopIcon color="warning" fontSize="small" titleAccess="stuck (looping)" />
                    </Tooltip>
                  )}
                </Stack>
              </TableCell>
              <TableCell align="right">{r.rep}</TableCell>
              <TableCell><VerifyCell row={r} reverify={reverify} /></TableCell>
              <TableCell>
                {r.success == null
                  ? "—"
                  : r.success
                    ? <CheckCircleIcon color="success" fontSize="small" titleAccess="success" />
                    : <CancelIcon color="error" fontSize="small" titleAccess="failed" />}
              </TableCell>
              <TableCell align="right" sx={selectable}>{num(r.duration_s, 1)}</TableCell>
              <TableCell align="right" sx={selectable}>{num(r.n_steps)}</TableCell>
              <TableCell align="right" sx={selectable}>{num(r.n_tool_calls)}</TableCell>
              <TableCell align="right" sx={selectable}>{num(r.n_test_runs)}</TableCell>
              <TableCell align="right" sx={selectable}>{num(r.cost, 4)}</TableCell>
            </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </Box>
  );
}
