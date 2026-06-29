import { useState } from "react";
import type { FieldProps } from "@rjsf/utils";
import {
  Stack, Typography, Button, Paper, IconButton, Chip, Box, Tooltip,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import EditIcon from "@mui/icons-material/Edit";
import DeleteIcon from "@mui/icons-material/Delete";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import ConditionModal, { type ConditionData, emptyCondition } from "./ConditionModal";

const ORCH_LABEL: Record<string, string> = {
  phased: "phased", phased_plan: "phased+plan",
  phased_graph: "phased+graph", phased_runtime: "phased+runtime",
};

function augChip(c: ConditionData): string {
  if (!c.augmentation) return "baseline";
  return c.augmentation_kind === "file" ? "file" : "inline";
}

export default function ConditionsField(props: FieldProps) {
  const value = (Array.isArray(props.formData) ? props.formData : []) as ConditionData[];
  const experimentName = (props.formContext as { formData?: { name?: string } })?.formData?.name;
  const [editing, setEditing] = useState<number | null>(null);

  const commit = (next: ConditionData[]) => props.onChange(next);
  const upsert = (c: ConditionData) => {
    const next = [...value];
    if (editing != null && editing < value.length) next[editing] = c;
    else next.push(c);
    commit(next);
    setEditing(null);
  };

  return (
    <Box>
      <Stack direction="row" alignItems="center" sx={{ mb: 1 }}>
        <Typography variant="subtitle1" sx={{ flexGrow: 1 }}>Conditions</Typography>
        <Button startIcon={<AddIcon />} size="small"
          onClick={() => setEditing(value.length)}>Add condition</Button>
      </Stack>
      <Stack spacing={1}>
        {value.map((c, i) => (
          <Paper key={i} variant="outlined" sx={{ p: 1, display: "flex", alignItems: "center", gap: 1 }}>
            <Typography sx={{ fontWeight: 600, minWidth: 120 }}>{c.name || `#${i + 1}`}</Typography>
            <Chip size="small" label={augChip(c)} />
            <Chip size="small" variant="outlined"
              label={c.tools.length ? `+${c.tools.join(",")}` : "no tools"} />
            <Chip size="small" variant="outlined"
              label={c.orchestration ? ORCH_LABEL[c.orchestration] ?? c.orchestration : "autonomous"} />
            {c.orchestration && <Chip size="small" variant="outlined" label={c.engine} />}
            {c.system_prompt && <Chip size="small" color="info" variant="outlined" label="sys override" />}
            <Box sx={{ flexGrow: 1 }} />
            <Tooltip title="Edit"><IconButton size="small" onClick={() => setEditing(i)}><EditIcon fontSize="small" /></IconButton></Tooltip>
            <Tooltip title="Duplicate"><IconButton size="small" onClick={() => {
              const copy = { ...c, name: `${c.name}-copy` };
              commit([...value.slice(0, i + 1), copy, ...value.slice(i + 1)]);
            }}><ContentCopyIcon fontSize="small" /></IconButton></Tooltip>
            <Tooltip title="Remove"><IconButton size="small" onClick={() => commit(value.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton></Tooltip>
          </Paper>
        ))}
        {value.length === 0 && (
          <Typography variant="body2" color="text.secondary">No conditions yet — add at least one (e.g. baseline).</Typography>
        )}
      </Stack>
      {editing != null && (
        <ConditionModal
          open
          key={editing}
          initial={value[editing] ?? emptyCondition(value.length === 0 ? "baseline" : "augmented")}
          experimentName={experimentName}
          onClose={() => setEditing(null)}
          onSave={upsert}
        />
      )}
    </Box>
  );
}
