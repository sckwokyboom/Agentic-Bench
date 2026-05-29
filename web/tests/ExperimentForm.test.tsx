import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ExperimentForm from "../src/components/ExperimentForm";

const trivialSchema = {
  type: "object",
  properties: {
    name: { type: "string", minLength: 1 },
    timeout_s: { type: "integer", minimum: 1 },
  },
  required: ["name", "timeout_s"],
};

test("rejects invalid form, Save disabled", async () => {
  const onSave = vi.fn();
  render(
    <ExperimentForm
      schema={trivialSchema as any}
      uiSchema={{}}
      formData={{ name: "", timeout_s: 0 }}
      onSave={onSave}
    />,
  );
  const saveBtn = await screen.findByRole("button", { name: /save/i });
  expect(saveBtn).toBeDisabled();
});

test("Save fires on valid form", async () => {
  const onSave = vi.fn();
  render(
    <ExperimentForm
      schema={trivialSchema as any}
      uiSchema={{}}
      formData={{ name: "ok", timeout_s: 5 }}
      onSave={onSave}
    />,
  );
  const saveBtn = await screen.findByRole("button", { name: /save/i });
  expect(saveBtn).not.toBeDisabled();
  await userEvent.click(saveBtn);
  expect(onSave).toHaveBeenCalledWith({ name: "ok", timeout_s: 5 });
});
