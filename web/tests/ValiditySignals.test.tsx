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

  it("shows a 'possible cheating' banner listing the signals", () => {
    render(
      <ValiditySignals
        cheating={{
          verdict: "suspicious",
          signals: [
            { type: "network", evidence: ["curl https://github.com/x"] },
            { type: "output_matches_original", evidence: ["99% similar to the reference method"] },
          ],
          target_similarity: 0.99,
        }}
      />,
    );
    expect(screen.getByText(/Possible cheating/i)).toBeInTheDocument();
    expect(screen.getByText(/network \/ upstream repo/i)).toBeInTheDocument();
    expect(screen.getByText(/near-identical to the reference/i)).toBeInTheDocument();
    expect(screen.getByText(/curl https:\/\/github\.com\/x/)).toBeInTheDocument();
  });

  it("ignores a clean cheating verdict", () => {
    const { container } = render(
      <ValiditySignals cheating={{ verdict: "clean", signals: [], target_similarity: null }} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when there are no signals", () => {
    const { container } = render(<ValiditySignals nServiceErrors={0} />);
    expect(container).toBeEmptyDOMElement();
  });
});
