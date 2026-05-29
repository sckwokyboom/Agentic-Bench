import { useState } from "react";
import { Stack, TextField, Chip, Box, Typography } from "@mui/material";

interface Props {
  value: string[];
  onChange: (next: string[]) => void;
  label?: string;
}

export default function TargetMethodsChips({ value, onChange, label = "Target methods" }: Props) {
  const [draft, setDraft] = useState("");
  return (
    <Stack spacing={1}>
      <Typography variant="caption">{label}</Typography>
      <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5 }}>
        {value.map((v, i) => (
          <Chip
            key={`${v}-${i}`}
            label={v}
            onDelete={() => onChange(value.filter((_, j) => j !== i))}
            size="small"
            deleteIcon={<span aria-label="delete">×</span>}
          />
        ))}
      </Box>
      <TextField
        size="small"
        placeholder="Add method (Enter to commit)"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && draft.trim()) {
            e.preventDefault();
            onChange([...value, draft.trim()]);
            setDraft("");
          }
        }}
      />
    </Stack>
  );
}
