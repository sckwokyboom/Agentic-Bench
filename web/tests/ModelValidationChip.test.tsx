import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { beforeEach } from "vitest";
import { mswServer } from "./setup";
import ModelValidationChip from "../src/components/ModelValidationChip";

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>;
}

// The component fetches the model catalog on mount; with msw set to error on
// unhandled requests, every test needs a /api/models handler. Default to a
// small catalog; individual tests can override.
beforeEach(() => {
  mswServer.use(http.get("/api/models", () =>
    HttpResponse.json([
      { provider: "openrouter", id: "openrouter/x" },
      { provider: "deepseek", id: "deepseek/deepseek-chat" },
    ])));
});

test("shows available + a success icon for backend status 'ok'", async () => {
  mswServer.use(http.post("/api/validate/model", () =>
    HttpResponse.json({ status: "ok", provider: "openrouter", suggestions: [] })));
  const { container } = render(wrap(<ModelValidationChip value="openrouter/foo" onChange={() => {}} />));
  await waitFor(() =>
    expect(screen.getByText(/available/i)).toBeInTheDocument(),
  );
  expect(container.querySelector('[data-testid="CheckCircleIcon"]')).not.toBeNull();
});

test("shows 'not in catalog' + a warning icon for 'model_not_found' with suggestions", async () => {
  mswServer.use(http.post("/api/validate/model", () =>
    HttpResponse.json({ status: "model_not_found", provider: "openrouter", suggestions: ["openrouter/foo-bar"] })));
  const { container } = render(wrap(<ModelValidationChip value="openrouter/foo-baz" onChange={() => {}} />));
  await waitFor(() =>
    expect(screen.getByText(/not in catalog/i)).toBeInTheDocument(),
  );
  expect(container.querySelector('[data-testid="WarningAmberIcon"]')).not.toBeNull();
  expect(screen.getByText("openrouter/foo-bar")).toBeInTheDocument();
});

test("shows 'no key' + a fail icon + Add API key for 'no_credentials'", async () => {
  mswServer.use(http.post("/api/validate/model", () =>
    HttpResponse.json({ status: "no_credentials", provider: "openrouter", suggestions: [] })));
  const { container } = render(wrap(<ModelValidationChip value="openrouter/foo" onChange={() => {}} />));
  await waitFor(() =>
    expect(container.querySelector('[data-testid="CancelIcon"]')).not.toBeNull(),
  );
  expect(screen.getByText("no key")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /add api key/i })).toBeInTheDocument();
});

test("shows 'malformed' + a warning icon for backend status 'malformed'", async () => {
  mswServer.use(http.post("/api/validate/model", () =>
    HttpResponse.json({ status: "malformed", provider: null, suggestions: [] })));
  const { container } = render(wrap(<ModelValidationChip value="bareid" onChange={() => {}} />));
  await waitFor(() =>
    expect(screen.getByText(/malformed/i)).toBeInTheDocument(),
  );
  expect(container.querySelector('[data-testid="WarningAmberIcon"]')).not.toBeNull();
});

test("autocomplete surfaces catalog options when opened", async () => {
  mswServer.use(http.post("/api/validate/model", () =>
    HttpResponse.json({ status: "ok", provider: "openrouter", suggestions: [] })));
  const user = userEvent.setup();
  render(wrap(<ModelValidationChip value="" onChange={() => {}} />));
  const input = await screen.findByRole("combobox");
  await user.click(input);
  // Options are grouped by provider; the catalog id should appear in the list.
  await waitFor(() =>
    expect(screen.getByText("openrouter/x")).toBeInTheDocument(),
  );
});

test("freeSolo: typing a custom provider/model still calls onChange with that value", async () => {
  mswServer.use(http.post("/api/validate/model", () =>
    HttpResponse.json({ status: "model_not_found", provider: "kimi", suggestions: [] })));
  const seen: string[] = [];
  const user = userEvent.setup();
  render(wrap(<ModelValidationChip value="" onChange={(v) => seen.push(v)} />));
  const input = await screen.findByRole("combobox");
  await user.type(input, "kimi/kimi-k2.6");
  expect(input).toHaveValue("kimi/kimi-k2.6");
  // The free-typed custom id (not in the catalog) was forwarded via onChange.
  expect(seen.some((v) => v === "kimi/kimi-k2.6")).toBe(true);
});
