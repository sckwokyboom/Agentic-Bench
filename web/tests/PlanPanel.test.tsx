import { render, screen } from "@testing-library/react";
import PlanPanel from "../src/components/PlanPanel";

test("shows total runs and ETA", () => {
  render(
    <PlanPanel formData={{
      conditions: [{ name: "a" }, { name: "b" }],
      reps_per_condition: 2,
      timeout_s: 60,
    }} />,
  );
  // "2 × 2 = 4 runs" is split across text nodes, so match on a function over the row's textContent.
  expect(
    screen.getByText((_, el) => el?.textContent === "2 × 2 = 4 runs"),
  ).toBeInTheDocument();
  // ETA: 2*2*60 = 240s → "4m"
  expect(screen.getByText(/est\. 4m at 60s\/run timeout/)).toBeInTheDocument();
});
