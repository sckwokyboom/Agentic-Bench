import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import SafeTraceButton from "../src/components/SafeTraceButton";

test("renders a batch safe-trace button with a custom label", () => {
  render(<SafeTraceButton name="exp" batch="b1" label="Safe traces" />);
  const btn = screen.getByRole("button", { name: /download safe trace/i });
  expect(btn).toBeEnabled();
  expect(btn).toHaveTextContent("Safe traces");
});

test("defaults the label to 'Safe trace' for a single run", () => {
  render(<SafeTraceButton name="exp" condition="baseline" rep={0} />);
  expect(
    screen.getByRole("button", { name: /download safe trace/i }),
  ).toHaveTextContent("Safe trace");
});
