import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import ProgressHeader from "../src/components/ProgressHeader";

const base = {
  runIdx: 1,
  totalRuns: 4,
  condition: "a",
  rep: 0,
  done: 1,
  running: 1,
  pending: 2,
  isolation: { nonce: true, shuffle: true },
};

describe("ProgressHeader verify badge", () => {
  it("renders passed/total with a failing status when there are failures", () => {
    render(
      <ProgressHeader
        {...base}
        verifyCounts={{ passed: 3, failed: 1, total: 4 }}
      />,
    );
    // total = passed + failed
    expect(screen.getByText(/3\/4/)).toBeInTheDocument();
    expect(screen.getByText(/1 failing/)).toBeInTheDocument();
  });

  it("renders a neutral 'no tests' badge when there are zero results", () => {
    render(
      <ProgressHeader
        {...base}
        verifyCounts={{ passed: 0, failed: 0, total: 0 }}
      />,
    );
    expect(screen.getByText(/no tests/i)).toBeInTheDocument();
    expect(screen.queryByText("0/0")).toBeNull();
  });

  it("renders passed/total with a passing status when all pass", () => {
    render(
      <ProgressHeader
        {...base}
        verifyCounts={{ passed: 4, failed: 0, total: 4 }}
      />,
    );
    expect(screen.getByText(/4\/4/)).toBeInTheDocument();
    expect(screen.queryByText(/failing/)).toBeNull();
  });
});
