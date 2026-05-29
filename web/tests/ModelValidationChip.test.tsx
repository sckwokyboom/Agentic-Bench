import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { mswServer } from "./setup";
import ModelValidationChip from "../src/components/ModelValidationChip";

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>;
}

test("shows ✓ available for backend status 'ok'", async () => {
  mswServer.use(http.post("/api/validate/model", () =>
    HttpResponse.json({ status: "ok", provider: "openrouter", suggestions: [] })));
  render(wrap(<ModelValidationChip value="openrouter/foo" onChange={() => {}} />));
  await waitFor(() =>
    expect(screen.getByText(/available/i)).toBeInTheDocument(),
  );
});

test("shows ⚠ not in catalog for 'model_not_found' with suggestions", async () => {
  mswServer.use(http.post("/api/validate/model", () =>
    HttpResponse.json({ status: "model_not_found", provider: "openrouter", suggestions: ["openrouter/foo-bar"] })));
  render(wrap(<ModelValidationChip value="openrouter/foo-baz" onChange={() => {}} />));
  await waitFor(() =>
    expect(screen.getByText(/not in catalog/i)).toBeInTheDocument(),
  );
  expect(screen.getByText("openrouter/foo-bar")).toBeInTheDocument();
});

test("shows ✗ no key + Add API key for 'no_credentials'", async () => {
  mswServer.use(http.post("/api/validate/model", () =>
    HttpResponse.json({ status: "no_credentials", provider: "openrouter", suggestions: [] })));
  render(wrap(<ModelValidationChip value="openrouter/foo" onChange={() => {}} />));
  await waitFor(() =>
    expect(screen.getByText(/no key/i)).toBeInTheDocument(),
  );
  expect(screen.getByRole("button", { name: /add api key/i })).toBeInTheDocument();
});

test("shows ⚠ malformed for backend status 'malformed'", async () => {
  mswServer.use(http.post("/api/validate/model", () =>
    HttpResponse.json({ status: "malformed", provider: null, suggestions: [] })));
  render(wrap(<ModelValidationChip value="bareid" onChange={() => {}} />));
  await waitFor(() =>
    expect(screen.getByText(/malformed/i)).toBeInTheDocument(),
  );
});
