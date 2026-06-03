import type { WidgetProps } from "@rjsf/utils";
import ModelValidationChip from "../components/ModelValidationChip";
import type { CustomEndpointInput } from "../components/CustomEndpointDialog";
import TargetMethodsChips from "../components/TargetMethodsChips";
import AugmentationField from "../components/AugmentationField";

export function ModelValidationWidget(props: WidgetProps) {
  return (
    <ModelValidationChip
      value={(props.value as string) ?? ""}
      onChange={(v) => props.onChange(v)}
      label={props.label}
      onAddCustomEndpoint={
        (props.formContext as { onAddCustomEndpoint?: (i: CustomEndpointInput) => void })
          ?.onAddCustomEndpoint
      }
    />
  );
}

export function TargetMethodsWidget(props: WidgetProps) {
  const arr = Array.isArray(props.value) ? (props.value as string[]) : [];
  return <TargetMethodsChips value={arr} onChange={props.onChange} label={props.label} />;
}

export function AugmentationWidget(props: WidgetProps) {
  return (
    <AugmentationField
      value={(props.value as string) ?? ""}
      onChange={props.onChange}
      label={props.label}
    />
  );
}
