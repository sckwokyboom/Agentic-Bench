import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import RunOptionsDialog from "../src/components/RunOptionsDialog";

describe("RunOptionsDialog", () => {
  const conditions = ["baseline", "augmented", "augmented-tool"];

  it("starts with the selected condition subset and repetitions", async () => {
    const onStart = vi.fn();
    render(
      <RunOptionsDialog
        open conditions={conditions} defaultReps={3} running={false}
        onClose={() => {}} onStart={onStart}
      />,
    );
    // all conditions checked by default → uncheck two, leaving augmented-tool
    await userEvent.click(screen.getByLabelText("baseline"));
    await userEvent.click(screen.getByLabelText("augmented"));
    const reps = screen.getByLabelText(/repetitions/i);
    await userEvent.clear(reps);
    await userEvent.type(reps, "1");
    await userEvent.click(screen.getByRole("button", { name: /start/i }));
    expect(onStart).toHaveBeenCalledWith({
      conditions: ["augmented-tool"],
      repetitions: 1,
    });
  });

  it("disables Start when no condition is selected", async () => {
    render(
      <RunOptionsDialog
        open conditions={["baseline"]} defaultReps={1} running={false}
        onClose={() => {}} onStart={() => {}}
      />,
    );
    await userEvent.click(screen.getByLabelText("baseline")); // uncheck the only one
    expect(screen.getByRole("button", { name: /start/i })).toBeDisabled();
  });
});
