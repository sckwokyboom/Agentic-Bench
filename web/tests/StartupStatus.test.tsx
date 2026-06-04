import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import StartupStatus from "../src/components/StartupStatus";

describe("StartupStatus", () => {
  it("renders the phase message and a spinner", () => {
    render(
      <StartupStatus
        status={{ kind: "preparing_workdir", message: "Preparing workdir…" }}
      />,
    );
    expect(screen.getByText("Preparing workdir…")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toBeInTheDocument();
    // Elapsed line starts at 0s.
    expect(screen.getByText(/0s elapsed/i)).toBeInTheDocument();
  });

  it("shows the retry counter for rate_limit_backoff", () => {
    render(
      <StartupStatus
        status={{
          kind: "rate_limit_backoff",
          message: "Rate limited…",
          retry: 2,
          maxRetries: 3,
        }}
      />,
    );
    expect(screen.getByText(/retry 2\/3/i)).toBeInTheDocument();
  });
});
