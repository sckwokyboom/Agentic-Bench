import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import VerifyChip from "../src/components/VerifyChip";

describe("VerifyChip", () => {
  it("shows passed/total when passing (no green 0/0)", () => {
    render(<VerifyChip status="passed" passed={3} failed={0} />);
    expect(screen.getByText(/3\/3/)).toBeInTheDocument();
    expect(screen.getByTestId("ScienceOutlinedIcon")).toBeInTheDocument();
  });

  it("shows passed/total and failing count when failed", () => {
    render(<VerifyChip status="failed" passed={3} failed={1} />);
    expect(screen.getByText(/3\/4/)).toBeInTheDocument();
    expect(screen.getByText(/1 failing/)).toBeInTheDocument();
  });

  it("renders a neutral 'no tests' chip rather than a green 0/0", () => {
    render(<VerifyChip status={null} passed={0} failed={0} />);
    expect(screen.getByText(/no tests/i)).toBeInTheDocument();
    expect(screen.queryByText("0/0")).toBeNull();
  });
});
