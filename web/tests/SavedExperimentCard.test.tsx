import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import SavedExperimentCard from "../src/components/SavedExperimentCard";

const formData = {
  model: "opencode/deepseek-v4-flash-free",
  conditions: [{ name: "baseline" }, { name: "augmented" }],
  repetitions: 3,
};

test("shows a saved confirmation + config summary and fires Run/Edit callbacks", async () => {
  const onRun = vi.fn();
  const onEdit = vi.fn();
  const { container } = render(
    <SavedExperimentCard
      name="demo" formData={formData} canRun running={false}
      onRun={onRun} onEdit={onEdit}
    />,
  );
  expect(screen.getByText("Saved")).toBeInTheDocument();
  expect(container.querySelector('[data-testid="CheckCircleIcon"]')).not.toBeNull();
  expect(screen.getByText(/2 conditions/)).toBeInTheDocument();
  expect(screen.getByText(/3 reps/)).toBeInTheDocument();
  expect(screen.getByText(/6 runs/)).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: /run experiment/i }));
  expect(onRun).toHaveBeenCalledOnce();
  await userEvent.click(screen.getByRole("button", { name: /edit again/i }));
  expect(onEdit).toHaveBeenCalledOnce();
});

test("disables Run and explains why when the experiment cannot run", () => {
  render(
    <SavedExperimentCard
      name="demo" formData={formData} canRun={false} running={false}
      onRun={() => {}} onEdit={() => {}}
    />,
  );
  expect(screen.getByRole("button", { name: /run experiment/i })).toBeDisabled();
  expect(screen.getByText(/Add a fixture/i)).toBeInTheDocument();
});

test("shows a starting state while a run is launching", () => {
  render(
    <SavedExperimentCard
      name="demo" formData={formData} canRun running
      onRun={() => {}} onEdit={() => {}}
    />,
  );
  expect(screen.getByRole("button", { name: /starting…/i })).toBeDisabled();
});
