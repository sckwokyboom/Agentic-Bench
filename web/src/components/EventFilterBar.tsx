import { Stack, FormControlLabel, Checkbox } from "@mui/material";

export type EventFilters = {
  reasoning: boolean;
  tool: boolean;
  text: boolean;
  error: boolean;
};

interface Props {
  value: EventFilters;
  onChange: (next: EventFilters) => void;
  autoScroll: boolean;
  onAutoScrollChange: (b: boolean) => void;
}

export default function EventFilterBar({ value, onChange, autoScroll, onAutoScrollChange }: Props) {
  function tog(k: keyof EventFilters) {
    return () => onChange({ ...value, [k]: !value[k] });
  }
  return (
    <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap" }}>
      <FormControlLabel control={<Checkbox size="small" checked={value.reasoning} onChange={tog("reasoning")} />} label="think" />
      <FormControlLabel control={<Checkbox size="small" checked={value.tool} onChange={tog("tool")} />} label="tool" />
      <FormControlLabel control={<Checkbox size="small" checked={value.text} onChange={tog("text")} />} label="text" />
      <FormControlLabel control={<Checkbox size="small" checked={value.error} onChange={tog("error")} />} label="err" />
      <FormControlLabel control={<Checkbox size="small" checked={autoScroll} onChange={() => onAutoScrollChange(!autoScroll)} />} label="auto-scroll" />
    </Stack>
  );
}
