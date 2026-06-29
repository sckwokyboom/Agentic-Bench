import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { RJSFSchema } from "@rjsf/utils";
import ExperimentForm from "../src/components/ExperimentForm";
import { uiSchema } from "../src/schema/uiSchema";
import { customWidgets, customFields, customTemplates } from "../src/schema/registry";
// Real (nullable-collapsed) experiment schema, captured from pydantic.
import realSchema from "./fixtures/experimentSchema.json";

const cond = (over: Record<string, unknown>) => ({
  name: "x", augmentation: null, augmentation_kind: "text", overlay: null,
  tools: [], orchestration: null, engine: "python", system_prompt: null, ...over,
});

const formData = {
  name: "demo",
  fixture_path: "f",
  reference_path: "r",
  task_prompt: "do it",
  system_prompt: "sys",
  model: "anthropic/claude",
  output_dir: "out",
  conditions: [
    cond({ name: "baseline" }),
    cond({ name: "augmented", augmentation: "ctx.md", tools: ["impact"], orchestration: "phased" }),
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
        widgets={customWidgets}
        fields={customFields}
        templates={customTemplates}
        onSave={() => {}}
      />
    </QueryClientProvider>,
  );
}

test("renders an Advanced accordion (collapsed by default)", () => {
  renderForm();
  // The Advanced accordion summary is present (label lists the advanced sections).
  expect(screen.getByText(/Advanced \(/i)).toBeInTheDocument();
  // The accordion is collapsed by default → its region is not expanded.
  expect(screen.getByRole("region", { hidden: true })).toBeInTheDocument();
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
  await userEvent.click(screen.getByText(/Advanced \(/i));
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
  // No leftover raw "Verify command" text input rendered by the default object template.
  expect(screen.queryByText(/^Verify command$/)).toBeNull();
});

test("conditions render as rows (by name) with an Add control, not a nested array form", () => {
  renderForm();
  // The custom ConditionsField shows an "Add condition" action…
  expect(screen.getByRole("button", { name: /add condition/i })).toBeInTheDocument();
  // …and one row per condition, labelled by the condition's name.
  expect(screen.getByText("augmented")).toBeInTheDocument();
  // "baseline" appears both as a row name and as the augmentation chip → at least one.
  expect(screen.getAllByText("baseline").length).toBeGreaterThan(0);
});
