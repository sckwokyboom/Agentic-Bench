import {
  Table, TableHead, TableBody, TableRow, TableCell, Typography, Box,
} from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import CancelIcon from "@mui/icons-material/Cancel";
import VerifyStatusChip from "./VerifyStatusChip";
import { selectable } from "../theme";
import type { RunSummary } from "../api/types";

interface Props {
  rows: RunSummary[];
  onOpen: (condition: string, rep: number) => void;
}

function num(v: number | null | undefined, digits = 0): string {
  return v == null ? "—" : v.toFixed(digits);
}

export default function RunsTable({ rows, onOpen }: Props) {
  if (rows.length === 0) {
    return <Typography variant="body2" color="text.secondary">No runs yet.</Typography>;
  }
  return (
    <Box sx={{ border: 1, borderColor: "divider", borderRadius: 1 }}>
      <Table size="small">
        <TableHead>
          <TableRow>
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
          {rows.map((r) => (
            <TableRow
              key={`${r.condition}-${r.rep}`}
              hover
              onClick={() => onOpen(r.condition, r.rep)}
              sx={{ cursor: "pointer" }}
            >
              <TableCell>{r.condition}</TableCell>
              <TableCell align="right">{r.rep}</TableCell>
              <TableCell><VerifyStatusChip status={r.verify_status} /></TableCell>
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
          ))}
        </TableBody>
      </Table>
    </Box>
  );
}
