/**
 * Pure merge for the "Add custom OpenAI endpoint" shortcut.
 *
 * Appends an OpenAI-compatible provider to `opencode.providers`, and points the
 * experiment's `model` (and opencode `small_model`) at it. The API key is NEVER
 * part of this merge — it goes only to opencode auth.json via writeCreds.
 */
export interface CustomEndpoint {
  id: string;
  baseUrl: string;
  model: string;
}

// Env var NAME the run delivers the auth.json key into (run_env reads the key by
// provider id and sets this var; build_opencode_config references it as
// {env:NAME} in options.apiKey). WITHOUT an api_key_env the key is never wired
// and opencode fails with "Failed to get the authorization header". The value is
// just a name — never the secret.
export function envNameForProvider(id: string): string {
  const base = id.toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  return `${base || "CUSTOM"}_API_KEY`;
}

export function applyCustomEndpoint(
  formData: Record<string, unknown>,
  { id, baseUrl, model }: CustomEndpoint,
): Record<string, unknown> {
  const provider = {
    id,
    base_url: baseUrl,
    models: [model],
    npm: "@ai-sdk/openai-compatible",
    api_key_env: envNameForProvider(id),
  };
  const oc = (formData.opencode as Record<string, unknown> | undefined) ?? {};
  const existing = oc.providers;
  const providers = Array.isArray(existing) ? existing : [];
  const ref = `${id}/${model}`;
  const nextOc = { ...oc, providers: [...providers, provider], small_model: ref };
  return { ...formData, model: ref, opencode: nextOc };
}
