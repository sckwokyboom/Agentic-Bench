import { TextField, MenuItem } from "@mui/material";

type Mode = "phased" | "phased_plan" | "phased_graph" | "phased_runtime" | null;

const OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Autonomous (none)" },
  { value: "phased", label: "Phased" },
  { value: "phased_plan", label: "Phased + plan" },
  { value: "phased_graph", label: "Phased + graph focus" },
  { value: "phased_runtime", label: "Phased + runtime evidence" },
];

interface Props {
  value: Mode;
  onChange: (next: Mode) => void;
  label?: string;
}

export default function OrchestrationSelect({ value, onChange, label = "Orchestration" }: Props) {
  return (
    <TextField
      select
      size="small"
      fullWidth
      label={label}
      value={value ?? ""}
      onChange={(e) => onChange((e.target.value || null) as Mode)}
      helperText="None = autonomous opencode loop. Phased modes need the experiment-level orchestration block."
    >
      {OPTIONS.map((o) => <MenuItem key={o.value} value={o.value}>{o.label}</MenuItem>)}
    </TextField>
  );
}
