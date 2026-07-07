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
  // Default to single-user mode; isolated-mode test overrides this.
  mswServer.use(http.get("/api/runtime-mode", () =>
    HttpResponse.json({ isolated: false })));
});

test("exposed/isolated mode: the key hint says it's per-session, not shared", async () => {
  mswServer.use(http.get("/api/runtime-mode", () =>
    HttpResponse.json({ isolated: true })));
  render(wrap(<ModelValidationChip value="deepseek/deepseek-chat" onChange={() => {}} />));
  await waitFor(() =>
    expect(screen.getByText(/session only/i)).toBeInTheDocument());
  expect(screen.getByRole("button", { name: /Set your session key/i })).toBeInTheDocument();
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
    expect(screen.getByText("not in catalog")).toBeInTheDocument(),
  );
  expect(container.querySelector('[data-testid="WarningAmberIcon"]')).not.toBeNull();
  expect(screen.getByText("openrouter/foo-bar")).toBeInTheDocument();
  // model_not_found is advisory too — the caption clarifies it doesn't block running.
  expect(screen.getByText(/advisory only/i)).toBeInTheDocument();
});

test("shows a neutral 'couldn't verify' chip + advisory caption for 'unverified' (no error/warning)", async () => {
  mswServer.use(http.post("/api/validate/model", () =>
    HttpResponse.json({ status: "unverified", provider: "deepseek", suggestions: [] })));
  const { container } = render(wrap(<ModelValidationChip value="deepseek/deepseek-chat" onChange={() => {}} />));
  await waitFor(() =>
    expect(screen.getByText(/couldn.?t verify/i)).toBeInTheDocument(),
  );
  // Neutral, not a scary false negative.
  expect(screen.queryByText("not in catalog")).toBeNull();
  expect(container.querySelector('[data-testid="WarningAmberIcon"]')).toBeNull();
  expect(container.querySelector('[data-testid="CancelIcon"]')).toBeNull();
  expect(container.querySelector('[data-testid="HelpOutlineIcon"]')).not.toBeNull();
  // Advisory caption is present.
  expect(screen.getByText(/advisory only/i)).toBeInTheDocument();
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

test("the '+ Add custom OpenAI endpoint' option is always present in the dropdown", async () => {
  mswServer.use(http.post("/api/validate/model", () =>
    HttpResponse.json({ status: "ok", provider: "openrouter", suggestions: [] })));
  const user = userEvent.setup();
  render(wrap(<ModelValidationChip value="" onChange={() => {}} />));
  const input = await screen.findByRole("combobox");
  await user.click(input);
  // Catalog is non-empty, yet the add-custom action is present.
  await waitFor(() =>
    expect(screen.getByText("openrouter/x")).toBeInTheDocument(),
  );
  expect(screen.getByText(/add custom openai endpoint/i)).toBeInTheDocument();
});

test("the add-custom option stays present even when the typed filter matches no catalog entry", async () => {
  mswServer.use(http.post("/api/validate/model", () =>
    HttpResponse.json({ status: "model_not_found", provider: "zzz", suggestions: [] })));
  const user = userEvent.setup();
  render(wrap(<ModelValidationChip value="" onChange={() => {}} />));
  const input = await screen.findByRole("combobox");
  await user.type(input, "zzz-no-such-model");
  // No catalog entry matches, but the add-custom action remains.
  expect(screen.getByText(/add custom openai endpoint/i)).toBeInTheDocument();
});

test("selecting the add-custom option opens the dialog without changing the model value", async () => {
  mswServer.use(http.post("/api/validate/model", () =>
    HttpResponse.json({ status: "ok", provider: "openrouter", suggestions: [] })));
  const seen: string[] = [];
  const user = userEvent.setup();
  render(wrap(<ModelValidationChip value="" onChange={(v) => seen.push(v)} />));
  const input = await screen.findByRole("combobox");
  await user.click(input);
  await user.click(await screen.findByText(/add custom openai endpoint/i));
  // Dialog fields are visible.
  expect(await screen.findByLabelText(/provider id/i)).toBeInTheDocument();
  expect(screen.getByLabelText(/base url/i)).toBeInTheDocument();
  expect(screen.getByLabelText(/model name/i)).toBeInTheDocument();
  // The model value was NOT changed to the sentinel.
  expect(seen.every((v) => v !== "__add_custom_endpoint__")).toBe(true);
  expect(input).toHaveValue("");
});

test("selecting add-custom does NOT clear an existing model value", async () => {
  mswServer.use(http.post("/api/validate/model", () =>
    HttpResponse.json({ status: "ok", provider: "openrouter", suggestions: [] })));
  const seen: string[] = [];
  const user = userEvent.setup();
  render(wrap(<ModelValidationChip value="openrouter/moonshotai/kimi-k2" onChange={(v) => seen.push(v)} />));
  const input = await screen.findByRole("combobox");
  await user.click(input);
  await user.click(await screen.findByText(/add custom openai endpoint/i));
  expect(await screen.findByLabelText(/provider id/i)).toBeInTheDocument();
  // The pre-existing model must be preserved (the sentinel's empty-label reset
  // must not wipe it), and onChange must never be called with "".
  expect(seen).not.toContain("");
  expect(input).toHaveValue("openrouter/moonshotai/kimi-k2");
});

test("filling the dialog + Add calls onAddCustomEndpoint with {id, baseUrl, model, apiKey}", async () => {
  mswServer.use(http.post("/api/validate/model", () =>
    HttpResponse.json({ status: "ok", provider: "openrouter", suggestions: [] })));
  const onAdd = vi.fn();
  const user = userEvent.setup();
  render(wrap(<ModelValidationChip value="" onChange={() => {}} onAddCustomEndpoint={onAdd} />));
  const input = await screen.findByRole("combobox");
  await user.click(input);
  await user.click(await screen.findByText(/add custom openai endpoint/i));
  await user.type(await screen.findByLabelText(/provider id/i), "myllm");
  await user.type(screen.getByLabelText(/base url/i), "http://10.0.0.5:8000/v1");
  await user.type(screen.getByLabelText(/model name/i), "my-model");
  await user.type(screen.getByLabelText(/api key/i), "sk-secret");
  await user.click(screen.getByRole("button", { name: /^add$/i }));
  expect(onAdd).toHaveBeenCalledWith({
    id: "myllm",
    baseUrl: "http://10.0.0.5:8000/v1",
    model: "my-model",
    apiKey: "sk-secret",
  });
});
