import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import TargetMethodsChips from "../src/components/TargetMethodsChips";

test("Enter appends a chip", async () => {
  const onChange = vi.fn();
  render(<TargetMethodsChips value={["foo"]} onChange={onChange} />);
  const input = screen.getByPlaceholderText(/add method/i);
  await userEvent.type(input, "bar{enter}");
  expect(onChange).toHaveBeenLastCalledWith(["foo", "bar"]);
});

test("delete removes the chip at its index", async () => {
  const onChange = vi.fn();
  render(<TargetMethodsChips value={["foo", "bar"]} onChange={onChange} />);
  const delBtns = screen.getAllByLabelText(/delete/i);
  await userEvent.click(delBtns[0]!);
  expect(onChange).toHaveBeenLastCalledWith(["bar"]);
});
