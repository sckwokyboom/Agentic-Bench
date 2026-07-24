import { useState } from "react";
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button, Stack, TextField,
} from "@mui/material";
import AugmentationField from "./AugmentationField";
import ToolsSelect from "./ToolsSelect";
import OrchestrationSelect from "./OrchestrationSelect";
import EngineSelect from "./EngineSelect";
import LongTextField from "./LongTextField";

export interface ConditionData {
  name: string;
  augmentation: string | null;
  augmentation_kind: "text" | "file";
  overlay: string | null;
  tools: string[];
  orchestration: "phased" | "phased_plan" | "phased_graph" | "phased_runtime" | "rcc" | null;
  engine: "python" | "langgraph";
  system_prompt: string | null;
  temperature: number | null;
}

export function emptyCondition(name = "baseline"): ConditionData {
  return {
    name, augmentation: null, augmentation_kind: "text", overlay: null,
    tools: [], orchestration: null, engine: "python", system_prompt: null,
    temperature: null,
  };
}

interface Props {
  open: boolean;
  initial: ConditionData;
  experimentName?: string;
  onClose: () => void;
  onSave: (c: ConditionData) => void;
}

export default function ConditionModal({ open, initial, experimentName, onClose, onSave }: Props) {
  const [c, setC] = useState<ConditionData>(initial);
  const set = <K extends keyof ConditionData,>(k: K, v: ConditionData[K]) =>
    setC((prev) => ({ ...prev, [k]: v }));

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="md">
      <DialogTitle>Condition: {c.name || "(unnamed)"}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField
            label="Name"
            size="small"
            value={c.name}
            onChange={(e) => set("name", e.target.value)}
            helperText="e.g. baseline, augmented"
          />
          <AugmentationField
            value={c.augmentation ?? ""}
            kind={c.augmentation_kind}
            experimentName={experimentName}
            onChange={(v, kind) => setC((p) => ({ ...p, augmentation: v || null, augmentation_kind: kind }))}
          />
          <ToolsSelect value={c.tools} onChange={(v) => set("tools", v)} />
          <Stack direction="row" spacing={2}>
            <OrchestrationSelect value={c.orchestration} onChange={(v) => set("orchestration", v)} />
            <EngineSelect
              value={c.engine}
              disabled={c.orchestration === null}
              onChange={(v) => set("engine", v)}
            />
          </Stack>
          <TextField
            label="Overlay directory (optional)"
            size="small"
            value={c.overlay ?? ""}
            onChange={(e) => set("overlay", e.target.value || null)}
            helperText="Per-session tool files copied into the workdir; blank = none."
          />
          <TextField
            label="Temperature (optional)"
            type="number"
            size="small"
            value={c.temperature ?? ""}
            onChange={(e) => {
              const n = Number(e.target.value);
              set("temperature", e.target.value === "" || !Number.isFinite(n) ? null : n);
            }}
            inputProps={{ min: 0, max: 2, step: 0.1 }}
            helperText="Sampling temperature 0–2 for this condition's agent; blank = provider default. Vary across conditions to A/B it."
          />
          <LongTextField
            label="System prompt override (optional)"
            value={c.system_prompt ?? ""}
            onChange={(v) => set("system_prompt", v || null)}
            helperText="Blank = use the experiment-level system prompt."
            rows={4}
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={!c.name.trim()} onClick={() => onSave(c)}>Save condition</Button>
      </DialogActions>
    </Dialog>
  );
}
