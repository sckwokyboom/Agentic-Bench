import { Chip } from "@mui/material";
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

export default function VerifyChip({ status, passed, failed }: Props) {
  if (!status) return <Chip size="small" label="🧪 pending" variant="outlined" />;
  if (status === "passed") {
    return <Chip size="small" color="success" label={`🧪 ${passed ?? "?"}/${passed ?? "?"}`} />;
  }
  if (status === "failed") {
    const total = (passed ?? 0) + (failed ?? 0);
    return <Chip size="small" color="error" label={`🧪 ${passed ?? "?"}/${total} (${failed ?? "?"} failing)`} />;
  }
  if (status === "running") return <Chip size="small" color="info" label="🧪 running…" />;
  return <Chip size="small" color={palette[status] ?? "default"} label={`🧪 ${status}`} />;
}
