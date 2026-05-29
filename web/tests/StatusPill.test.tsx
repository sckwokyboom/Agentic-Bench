import { render, screen } from "@testing-library/react";
import StatusPill from "../src/components/StatusPill";

test.each([
  ["ready",       /ready/i],
  ["no_fixture",  /no fixture/i],
  ["running",     /running/i],
] as const)("StatusPill renders %s", (status, label) => {
  render(<StatusPill status={status} />);
  expect(screen.getByText(label)).toBeInTheDocument();
});
