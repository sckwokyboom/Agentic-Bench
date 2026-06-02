import type { UiSchema } from "@rjsf/utils";
import ConditionItemTemplate from "./ConditionItemTemplate";

// Custom widget names must match the keys we register on the Form's `widgets` prop.
export const uiSchema: UiSchema = {
  "ui:submitButtonOptions": { norender: true },
  // Core fields first; remaining (advanced) fields fall under "*", which the
  // RootObjectFieldTemplate routes into the collapsible Advanced accordion.
  "ui:order": [
    "name", "model", "task_prompt", "system_prompt", "conditions",
    "repetitions", "verify", "*",
  ],
  model:       { "ui:widget": "ModelValidationWidget" },
  target_methods: { "ui:widget": "TargetMethodsWidget" },
  // v2 forward-compat fields — hide from v1 UI.
  isolation: {
    user_field_template: { "ui:widget": "hidden" },
    api_key_env_list:    { "ui:widget": "hidden" },
  },
  conditions: {
    // Title each condition by its `name` value rather than its index. The
    // ArrayFieldItemTemplate override is resolved from the ARRAY-level uiSchema
    // (rjsf 5.24 reads it via getUiOptions(uiSchema) in ArrayFieldTemplate), so
    // it must live here, not under `items`.
    "ui:ArrayFieldItemTemplate": ConditionItemTemplate,
    items: {
      augmentation: { "ui:widget": "AugmentationWidget" },
    },
  },
  // String-array metric knobs: keep the array's human title+description (from the
  // schema), but drop the redundant per-item "<name>-0 *" row labels.
  metrics: {
    test_command_patterns: { items: { "ui:options": { label: false } } },
    shell_tool_names: { items: { "ui:options": { label: false } } },
    read_tool_names: { items: { "ui:options": { label: false } } },
    search_tool_names: { items: { "ui:options": { label: false } } },
    command_arg_keys: { items: { "ui:options": { label: false } } },
  },
  // System prompt + user message can be long → multiline.
  system_prompt: { "ui:widget": "textarea", "ui:options": { rows: 10 } },
  user_message: { "ui:widget": "textarea", "ui:options": { rows: 6 } },
  // VerifyField owns the entire verify object rendering (build-system dropdown,
  // enabled switch, timeout). This replaces the old raw command help/placeholder.
  verify: { "ui:field": "VerifyField" },
};
