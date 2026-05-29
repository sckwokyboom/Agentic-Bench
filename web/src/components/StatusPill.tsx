import { Chip } from "@mui/material";

export type ExperimentStatus = "ready" | "no_fixture" | "running";

interface Props { status: ExperimentStatus; }

const map: Record<ExperimentStatus, { label: string; color: "success" | "warning" | "info" }> = {
  ready:      { label: "ready",      color: "success" },
  no_fixture: { label: "no fixture", color: "warning" },
  running:    { label: "running",    color: "info" },
};

export default function StatusPill({ status }: Props) {
  const { label, color } = map[status];
  return <Chip size="small" label={label} color={color} variant="outlined" />;
}
