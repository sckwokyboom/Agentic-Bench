import type { WidgetProps } from "@rjsf/utils";
import ModelValidationChip from "../components/ModelValidationChip";
import TargetMethodsChips from "../components/TargetMethodsChips";

export function ModelValidationWidget(props: WidgetProps) {
  return (
    <ModelValidationChip
      value={(props.value as string) ?? ""}
      onChange={(v) => props.onChange(v)}
      label={props.label}
    />
  );
}

export function TargetMethodsWidget(props: WidgetProps) {
  const arr = Array.isArray(props.value) ? (props.value as string[]) : [];
  return <TargetMethodsChips value={arr} onChange={props.onChange} label={props.label} />;
}
