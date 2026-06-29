import type { WidgetProps } from "@rjsf/utils";
import ModelValidationChip from "../components/ModelValidationChip";
import type { CustomEndpointInput } from "../components/CustomEndpointDialog";
import TargetMethodsChips from "../components/TargetMethodsChips";
import LongTextField from "../components/LongTextField";
import ContextWindowField from "../components/ContextWindowField";

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

export function LongTextWidget(props: WidgetProps) {
  return (
    <LongTextField
      value={(props.value as string) ?? ""}
      onChange={(v) => props.onChange(v)}
      label={props.label}
      helperText={props.schema.description as string | undefined}
    />
  );
}

export function ContextWindowWidget(props: WidgetProps) {
  const fc = (props.formContext ?? {}) as {
    formData?: { model?: string; opencode?: { providers?: unknown[] } };
  };
  return (
    <ContextWindowField
      value={(props.value as number | null) ?? null}
      onChange={(v) => props.onChange(v)}
      label={props.label}
      model={fc.formData?.model}
      providers={(fc.formData?.opencode?.providers as never[]) ?? []}
    />
  );
}
