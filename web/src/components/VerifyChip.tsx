import { Chip } from "@mui/material";
import ScienceOutlinedIcon from "@mui/icons-material/ScienceOutlined";
import type { VerifyStatus } from "../api/types";

interface Props {
  status: VerifyStatus | "running" | null | undefined;
  passed?: number | null;
  failed?: number | null;
}

const palette: Record<string, "success" | "error" | "warning" | "info" | "default"> = {
  passed: "success",
  failed: "error",
  skipped: "default",
  timeout: "warning",
  error: "warning",
  running: "info",
};

const sci = <ScienceOutlinedIcon fontSize="inherit" />;

export default function VerifyChip({ status, passed, failed }: Props) {
  const p = passed ?? 0;
  const f = failed ?? 0;
  const total = p + f;

  if (!status) {
    // No verify result yet — neutral, never a green 0/0.
    return (
      <Chip size="small" icon={sci} label="no tests" variant="outlined" />
    );
  }
  if (status === "running") {
    return <Chip size="small" color="info" icon={sci} label="running…" />;
  }
  if (status === "passed") {
    if (total === 0) {
      return (
        <Chip size="small" icon={sci} label="no tests" variant="outlined" />
      );
    }
    return <Chip size="small" color="success" icon={sci} label={`${p}/${total}`} />;
  }
  if (status === "failed") {
    return (
      <Chip
        size="small"
        color="error"
        icon={sci}
        label={`${p}/${total} (${f} failing)`}
      />
    );
  }
  return (
    <Chip size="small" color={palette[status] ?? "default"} icon={sci} label={status} />
  );
}
