import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { RJSFSchema } from "@rjsf/utils";
import ExperimentForm from "../src/components/ExperimentForm";
import { uiSchema } from "../src/schema/uiSchema";
import {
  ModelValidationWidget, TargetMethodsWidget, AugmentationWidget,
} from "../src/schema/widgets";
import RootObjectFieldTemplate from "../src/schema/RootObjectFieldTemplate";
import VerifyField from "../src/components/VerifyField";
// Real (nullable-collapsed) experiment schema, captured from pydantic.
import realSchema from "./fixtures/experimentSchema.json";

const widgets = { ModelValidationWidget, TargetMethodsWidget, AugmentationWidget };
const fields = { VerifyField };
const templates = { ObjectFieldTemplate: RootObjectFieldTemplate };

const formData = {
  name: "demo",
  fixture_path: "f",
  reference_path: "r",
  task_prompt: "do it",
  system_prompt: "sys",
  model: "anthropic/claude",
  output_dir: "out",
  conditions: [
    { name: "baseline", augmentation: null },
    { name: "augmented", augmentation: "ctx.md" },
  ],
  repetitions: 1,
  verify: { command: null, enabled: true, timeout_s: 300 },
};

function renderForm() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ExperimentForm
        schema={realSchema as unknown as RJSFSchema}
        uiSchema={uiSchema}
        formData={formData}
        widgets={widgets}
        fields={fields}
        templates={templates}
        onSave={() => {}}
      />
    </QueryClientProvider>,
  );
}

test("renders an Advanced accordion with metrics/isolation inside it (collapsed by default)", () => {
  renderForm();
  // The Advanced accordion summary is present.
  const summary = screen.getByText(/Advanced \(metrics, isolation, paths, tuning\)/i);
  expect(summary).toBeInTheDocument();

  // The accordion is collapsed by default → its region is not expanded.
  const region = screen.getByRole("region", { hidden: true });
  expect(region).toBeInTheDocument();
});

test("a core field (name) is visible at the top without expanding Advanced", () => {
  renderForm();
  // Target the root experiment name input specifically (id root_name); a bare
  // /name/i would also match the per-condition Name field.
  const nameInput = document.getElementById("root_name") as HTMLInputElement | null;
  expect(nameInput).not.toBeNull();
  expect(nameInput?.value).toBe("demo");
});

test("metrics/isolation controls live inside the Advanced region", async () => {
  renderForm();
  // Expand the accordion.
  await userEvent.click(screen.getByText(/Advanced \(metrics, isolation, paths, tuning\)/i));
  // After expanding, an isolation control (Nonce prefix) becomes reachable.
  const region = screen.getByRole("region");
  expect(within(region).getByText(/Nonce prefix/i)).toBeInTheDocument();
  // A metrics array title is also under Advanced.
  expect(within(region).getByText(/Test command patterns/i)).toBeInTheDocument();
});

test("the verify section is a Build system dropdown, not a raw command anyOf picker", () => {
  renderForm();
  // Build system Select present.
  expect(screen.getByRole("combobox", { name: /build system/i })).toBeInTheDocument();
  // No leftover anyOf type-picker for verify.command: there must be no select
  // whose options include the bare "string"/"null" type-picker entries, and no
  // raw "Verify command" text input rendered by the default object template.
  expect(screen.queryByText(/^Verify command$/)).toBeNull();
});

test("conditions are titled by their name, not by index", () => {
  renderForm();
  // The label is "Condition: " + the data-derived name, rendered as two text
  // nodes inside one element, so match on the element's full textContent.
  const byText = (re: RegExp) =>
    screen.getByText((_content, el) => !!el && re.test(el.textContent ?? ""));
  expect(byText(/^Condition: baseline$/)).toBeInTheDocument();
  expect(byText(/^Condition: augmented$/)).toBeInTheDocument();
});
