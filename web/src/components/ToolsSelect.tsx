import { Autocomplete, TextField, Chip } from "@mui/material";

// Curated list: opencode built-ins worth gating + the gateable library tools.
// freeSolo lets an unknown tool still be typed.
const KNOWN_TOOLS = ["impact", "read", "grep", "glob", "list", "edit", "write", "bash"];

interface Props {
  value: string[];
  onChange: (next: string[]) => void;
  label?: string;
}

export default function ToolsSelect({ value, onChange, label = "Enabled tools" }: Props) {
  return (
    <Autocomplete
      multiple
      freeSolo
      size="small"
      options={KNOWN_TOOLS}
      value={value}
      onChange={(_e, v) => onChange(v as string[])}
      renderTags={(vals, getTagProps) =>
        vals.map((opt, i) => <Chip size="small" label={opt} {...getTagProps({ index: i })} key={opt} />)
      }
      renderInput={(params) => (
        <TextField
          {...params}
          label={label}
          helperText="A tool from opencode.tools_lib NOT listed here is disabled for this condition (preserves the A/B contrast)."
        />
      )}
    />
  );
}
