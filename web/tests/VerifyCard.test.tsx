import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import VerifyCard from "../src/components/VerifyCard";
import type { Trace } from "../src/api/types";

const failed: Trace = {
  turns: [], verify_status: "failed", verify_command: "pytest",
  verify_duration_s: 3, verify_passed_count: 8, verify_failed_count: 2,
  verify_failed_names: ["test_a", "test_b"], verify_baseline_unknown: false,
  isolation_nonce: null, final_diff_summary: null,
};

test("shows command, counts, expands failing names", async () => {
  render(<VerifyCard trace={failed} />);
  expect(screen.getByText(/pytest/)).toBeInTheDocument();
  expect(screen.getByText(/8\/10/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /show 2 failing/i }));
  expect(screen.getByText("— test_a")).toBeInTheDocument();
});

test("renders nothing when verify_status is null", () => {
  const { container } = render(
    <VerifyCard trace={{ ...failed, verify_status: null }} />,
  );
  expect(container.firstChild).toBeNull();
});
