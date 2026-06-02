import { render, screen } from "@testing-library/react";
import VerdictBanner from "../src/components/VerdictBanner";
import type { Trace } from "../src/api/types";

const base: Trace = {
  steps: [], turns: [], verify_status: "passed", verify_command: "pytest",
  verify_duration_s: 1.2, verify_passed_count: 5, verify_failed_count: 0,
  verify_failed_names: [], verify_baseline_unknown: false,
  isolation_nonce: null, final_diff_summary: null,
};

test("passed banner", () => {
  const { container } = render(<VerdictBanner trace={base} />);
  expect(screen.getByText(/Verified/)).toBeInTheDocument();
  expect(container.querySelector('[data-testid="CheckCircleIcon"]')).not.toBeNull();
});

test("failed banner", () => {
  const { container } = render(
    <VerdictBanner trace={{ ...base, verify_status: "failed", verify_passed_count: 3, verify_failed_count: 2 }} />,
  );
  expect(screen.getByText(/Verify failed/)).toBeInTheDocument();
  expect(container.querySelector('[data-testid="CancelIcon"]')).not.toBeNull();
  expect(screen.getByText(/3\/5/)).toBeInTheDocument();
});

test("error banner", () => {
  const { container } = render(
    <VerdictBanner trace={{ ...base, verify_status: "error", verify_message: "boom" }} />,
  );
  expect(screen.getByText(/Verify error/)).toBeInTheDocument();
  expect(container.querySelector('[data-testid="WarningAmberIcon"]')).not.toBeNull();
});
