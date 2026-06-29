import { TextField, MenuItem } from "@mui/material";

type Engine = "python" | "langgraph";

interface Props {
  value: Engine;
  onChange: (next: Engine) => void;
  disabled?: boolean;
  label?: string;
}

export default function EngineSelect({ value, onChange, disabled, label = "Engine" }: Props) {
  return (
    <TextField
      select
      size="small"
      fullWidth
      label={label}
      value={value ?? "python"}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value as Engine)}
      helperText={disabled ? "Applies only to phased modes." : "Phased controller implementation."}
    >
      <MenuItem value="python">Python</MenuItem>
      <MenuItem value="langgraph">LangGraph</MenuItem>
    </TextField>
  );
}
