import { render, screen } from "@testing-library/react";
import type { DescriptionFieldProps } from "@rjsf/utils";
import DescriptionFieldTemplate from "../src/schema/DescriptionFieldTemplate";

// Minimal rjsf DescriptionFieldProps; only `description` is read by the template.
function props(description: DescriptionFieldProps["description"]): DescriptionFieldProps {
  return {
    id: "root_x__description",
    description,
    schema: {},
    registry: {} as DescriptionFieldProps["registry"],
  };
}

test("renders the description as small grey caption text", () => {
  render(<DescriptionFieldTemplate {...props("How many times each condition runs.")} />);
  const el = screen.getByText("How many times each condition runs.");
  expect(el).toBeInTheDocument();
  // MUI caption renders as a <span> with the caption typography class.
  expect(el.tagName).toBe("SPAN");
  expect(el.className).toMatch(/MuiTypography-caption/);
});

test("renders nothing when description is empty", () => {
  const { container } = render(<DescriptionFieldTemplate {...props("")} />);
  expect(container.firstChild).toBeNull();
});
