import type { UiSchema } from "@rjsf/utils";

// Custom widget names must match the keys we register on the Form's `widgets` prop.
export const uiSchema: UiSchema = {
  "ui:submitButtonOptions": { norender: true },
  model:       { "ui:widget": "ModelValidationWidget" },
  small_model: { "ui:widget": "ModelValidationWidget" },
  target_methods: { "ui:widget": "TargetMethodsWidget" },
  // v2 forward-compat fields — hide from v1 UI.
  isolation: {
    user_field_template: { "ui:widget": "hidden" },
    api_key_env_list:    { "ui:widget": "hidden" },
  },
  conditions: {
    items: {
      augmentation: { "ui:widget": "AugmentationWidget" },
    },
  },
  // System prompt + user message can be long → multiline.
  system_prompt: { "ui:widget": "textarea", "ui:options": { rows: 10 } },
  user_message: { "ui:widget": "textarea", "ui:options": { rows: 6 } },
  verify: {
    command: {
      "ui:help": "Build/test command. Leave blank to auto-detect; override for e.g. ./gradlew test, mvn -q test, pytest -q.",
      "ui:placeholder": "auto-detect",
    },
  },
};
