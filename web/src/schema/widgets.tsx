import type { WidgetProps } from "@rjsf/utils";
import ModelValidationChip from "../components/ModelValidationChip";

export function ModelValidationWidget(props: WidgetProps) {
  return (
    <ModelValidationChip
      value={(props.value as string) ?? ""}
      onChange={(v) => props.onChange(v)}
      label={props.label}
    />
  );
}
