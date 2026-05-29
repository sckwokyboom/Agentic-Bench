import { Chip } from "@mui/material";
import type { VerifyStatus } from "../api/types";

const color: Record<string, "success" | "error" | "warning" | "default"> = {
  passed: "success", failed: "error", timeout: "warning", error: "warning", skipped: "default",
};

export default function VerifyStatusChip({ status }: { status: VerifyStatus | null }) {
  if (!status) return <Chip size="small" variant="outlined" label="—" />;
  return <Chip size="small" color={color[status] ?? "default"} label={status} />;
}
