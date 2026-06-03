import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import ValiditySignals from "../src/components/ValiditySignals";

describe("ValiditySignals", () => {
  it("shows a service-errors banner with the count", () => {
    render(<ValiditySignals nServiceErrors={3} />);
    const banner = screen.getByText(/3 service\/proxy errors/i);
    expect(banner).toBeInTheDocument();
  });

  it("shows the interrupted_reason in the error banner", () => {
    render(<ValiditySignals nServiceErrors={1} interruptedReason="rate_limit" />);
    expect(screen.getByText(/rate_limit/)).toBeInTheDocument();
  });

  it("lists up to 3 service error messages", () => {
    render(
      <ValiditySignals
        nServiceErrors={5}
        serviceErrorMessages={["err one", "err two", "err three", "err four"]}
      />,
    );
    expect(screen.getByText(/err one/)).toBeInTheDocument();
    expect(screen.getByText(/err three/)).toBeInTheDocument();
    expect(screen.queryByText(/err four/)).toBeNull();
  });

  it("shows an error banner when interrupted_reason is set even with zero errors", () => {
    render(<ValiditySignals nServiceErrors={0} interruptedReason="timeout" />);
    expect(screen.getByText(/timeout/)).toBeInTheDocument();
  });

  it("shows the verify-insensitivity banner when verifyInsensitive", () => {
    render(<ValiditySignals verifyInsensitive />);
    expect(
      screen.getByText(/Verify can't distinguish agent work/i),
    ).toBeInTheDocument();
  });

  it("renders nothing when there are no signals", () => {
    const { container } = render(<ValiditySignals nServiceErrors={0} />);
    expect(container).toBeEmptyDOMElement();
  });
});
