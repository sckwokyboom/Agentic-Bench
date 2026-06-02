import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import IsolationChip from "../src/components/IsolationChip";

describe("IsolationChip", () => {
  it("renders a Lock icon when both nonce and shuffle are on", () => {
    render(<IsolationChip nonce shuffle />);
    expect(screen.getByTestId("LockIcon")).toBeInTheDocument();
    expect(screen.queryByTestId("LockOpenIcon")).toBeNull();
  });

  it("renders a LockOpen icon when both are off", () => {
    render(<IsolationChip nonce={false} shuffle={false} />);
    expect(screen.getByTestId("LockOpenIcon")).toBeInTheDocument();
    expect(screen.queryByTestId("LockIcon")).toBeNull();
  });

  it("reflects prop values (one only -> partial, locked)", () => {
    render(<IsolationChip nonce shuffle={false} />);
    // Partially isolated is still a "locked" affordance.
    expect(screen.getByTestId("LockIcon")).toBeInTheDocument();
    expect(screen.getByText(/nonce only/i)).toBeInTheDocument();
  });

  it("exposes an explanatory tooltip (nonce + shuffle meaning)", async () => {
    render(<IsolationChip nonce shuffle />);
    // The tooltip title is wired via aria-label on the wrapper so it is
    // assertable without hover simulation.
    const tip = screen.getByLabelText(/nonce =/i);
    expect(tip).toBeInTheDocument();
    expect(tip.getAttribute("aria-label") ?? "").toMatch(/shuffle =/i);
  });
});
