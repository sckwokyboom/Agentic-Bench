import type { UiSchema } from "@rjsf/utils";

// Custom widget names must match the keys we register on the Form's `widgets` prop.
export const uiSchema: UiSchema = {
  "ui:submitButtonOptions": { norender: true },
  // Core fields first; remaining (advanced) fields fall under "*", which the
  // RootObjectFieldTemplate routes into the collapsible Advanced accordion.
  "ui:order": [
    "name", "fixture_path", "reference_path", "model",
    "task_prompt", "system_prompt", "conditions",
    "repetitions", "verify", "*",
  ],
  model:       { "ui:widget": "ModelValidationWidget" },
  model_context_window: { "ui:widget": "ContextWindowWidget" },
  target_methods: { "ui:widget": "TargetMethodsWidget" },
  // v2 forward-compat fields — hide from v1 UI.
  isolation: {
    user_field_template: { "ui:widget": "hidden" },
    api_key_env_list:    { "ui:widget": "hidden" },
  },
  conditions: { "ui:field": "ConditionsField" },
  // String-array metric knobs: keep the array's human title+description (from the
  // schema), but drop the redundant per-item "<name>-0 *" row labels.
  metrics: {
    test_command_patterns: { items: { "ui:options": { label: false } } },
    shell_tool_names: { items: { "ui:options": { label: false } } },
    read_tool_names: { items: { "ui:options": { label: false } } },
    search_tool_names: { items: { "ui:options": { label: false } } },
    command_arg_keys: { items: { "ui:options": { label: false } } },
  },
  // opencode: custom providers (OpenAI-compatible endpoints) + small_model override.
  // Drop the redundant per-item row labels on each provider's `models` string-array.
  opencode: {
    providers: {
      items: {
        models: { items: { "ui:options": { label: false } } },
      },
    },
  },
  // Task/system prompts can be long → expandable editor.
  task_prompt:   { "ui:widget": "LongTextWidget" },
  system_prompt: { "ui:widget": "LongTextWidget" },
  // VerifyField owns the entire verify object rendering (build-system dropdown,
  // enabled switch, timeout). This replaces the old raw command help/placeholder.
  verify: { "ui:field": "VerifyField" },
};
