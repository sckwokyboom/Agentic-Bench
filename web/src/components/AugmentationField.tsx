import { TextField } from "@mui/material";

interface Props {
  value: string;
  onChange: (next: string) => void;
  label?: string;
}

export default function AugmentationField({ value, onChange, label = "Augmentation" }: Props) {
  return (
    <TextField
      label={label}
      multiline
      minRows={6}
      fullWidth
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value)}
      helperText="Saved as slices/<condition>.md on PUT."
    />
  );
}
