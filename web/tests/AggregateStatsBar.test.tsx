import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import AggregateStatsBar from "../src/components/AggregateStatsBar";
import type { MetricsJson } from "../src/api/types";

const base: MetricsJson = {
  finished: true,
  interrupted_reason: null,
  success: true,
  verify_status: "passed",
  verify_command: null,
  verify_duration_s: null,
  verify_passed_count: null,
  verify_failed_count: null,
};

// The cost <Typography> renders "cost: <value>"; match that whole node.
const costNode = (content: string, el: Element | null) =>
  el?.tagName.toLowerCase() === "p" && /^cost:\s/.test((el.textContent ?? "").trim());

test("renders — for cost when cost is absent", () => {
  render(<AggregateStatsBar metrics={base} />);
  expect(screen.getByText(costNode)).toHaveTextContent("cost: —");
});

test("renders $value for cost when present", () => {
  render(<AggregateStatsBar metrics={{ ...base, cost: 0.0123 }} />);
  expect(screen.getByText(costNode)).toHaveTextContent("cost: $0.0123");
});
