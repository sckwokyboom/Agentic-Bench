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

describe("ProgressHeader service-errors chip", () => {
  it("renders a red 'N errors' chip when serviceErrors > 0", () => {
    render(
      <ProgressHeader
        {...base}
        verifyCounts={{ passed: 4, failed: 0, total: 4 }}
        serviceErrors={2}
      />,
    );
    expect(screen.getByText(/2 errors/i)).toBeInTheDocument();
  });

  it("renders no errors chip when serviceErrors is 0", () => {
    render(
      <ProgressHeader
        {...base}
        verifyCounts={{ passed: 4, failed: 0, total: 4 }}
        serviceErrors={0}
      />,
    );
    expect(screen.queryByText(/errors/i)).toBeNull();
  });

  it("renders no errors chip when serviceErrors is undefined", () => {
    render(
      <ProgressHeader
        {...base}
        verifyCounts={{ passed: 4, failed: 0, total: 4 }}
      />,
    );
    expect(screen.queryByText(/errors/i)).toBeNull();
  });
});

describe("ProgressHeader token totals", () => {
  it("shows Σ in / Σ out when tokens are present", () => {
    render(
      <ProgressHeader
        {...base}
        verifyCounts={{ passed: 0, failed: 0, total: 0 }}
        tokens={{ inSum: 12345, outSum: 678 }}
      />,
    );
    expect(screen.getByText(/Σ in/)).toBeInTheDocument();
    expect(screen.getByText(/Σ out/)).toBeInTheDocument();
  });

  it("renders no token line when tokens are null or all zero", () => {
    const { rerender } = render(
      <ProgressHeader {...base} verifyCounts={{ passed: 0, failed: 0, total: 0 }} tokens={null} />,
    );
    expect(screen.queryByText(/Σ in/)).toBeNull();
    rerender(
      <ProgressHeader {...base} verifyCounts={{ passed: 0, failed: 0, total: 0 }} tokens={{ inSum: 0, outSum: 0 }} />,
    );
    expect(screen.queryByText(/Σ in/)).toBeNull();
  });
});

describe("ProgressHeader ETA line", () => {
  it("shows total + remaining when the estimate is ready", () => {
    render(
      <ProgressHeader
        {...base}
        verifyCounts={{ passed: 0, failed: 0, total: 0 }}
        estimate={{ state: "ready", totalRuns: 6, doneRuns: 2, etaSeconds: 360, totalSeconds: 600 }}
      />,
    );
    expect(screen.getByText(/≈ ~10m total · ~6m left · 2\/6 runs/i)).toBeInTheDocument();
  });

  it("shows 'Estimating run time…' before the first run finishes", () => {
    render(
      <ProgressHeader
        {...base}
        verifyCounts={{ passed: 0, failed: 0, total: 0 }}
        estimate={{ state: "estimating", totalRuns: 6, doneRuns: 0, etaSeconds: null, totalSeconds: null }}
      />,
    );
    expect(screen.getByText(/Estimating run time…/i)).toBeInTheDocument();
  });

  it("renders no ETA line when idle or done", () => {
    const { rerender } = render(
      <ProgressHeader
        {...base}
        verifyCounts={{ passed: 0, failed: 0, total: 0 }}
        estimate={{ state: "idle", totalRuns: 0, doneRuns: 0, etaSeconds: null, totalSeconds: null }}
      />,
    );
    expect(screen.queryByText(/total ·|Estimating/i)).toBeNull();
    rerender(
      <ProgressHeader
        {...base}
        verifyCounts={{ passed: 0, failed: 0, total: 0 }}
        estimate={{ state: "done", totalRuns: 6, doneRuns: 6, etaSeconds: 0, totalSeconds: 600 }}
      />,
    );
    expect(screen.queryByText(/total ·|Estimating/i)).toBeNull();
  });
});
