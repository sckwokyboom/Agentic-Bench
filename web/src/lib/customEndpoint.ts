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

export function applyCustomEndpoint(
  formData: Record<string, unknown>,
  { id, baseUrl, model }: CustomEndpoint,
): Record<string, unknown> {
  const provider = {
    id,
    base_url: baseUrl,
    models: [model],
    npm: "@ai-sdk/openai-compatible",
  };
  const oc = (formData.opencode as Record<string, unknown> | undefined) ?? {};
  const existing = oc.providers;
  const providers = Array.isArray(existing) ? existing : [];
  const ref = `${id}/${model}`;
  const nextOc = { ...oc, providers: [...providers, provider], small_model: ref };
  return { ...formData, model: ref, opencode: nextOc };
}
