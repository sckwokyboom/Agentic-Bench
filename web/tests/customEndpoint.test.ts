import { applyCustomEndpoint } from "../src/lib/customEndpoint";

const ep = { id: "myllm", baseUrl: "http://10.0.0.5:8000/v1", model: "my-model" };
const provider = {
  id: "myllm",
  base_url: "http://10.0.0.5:8000/v1",
  models: ["my-model"],
  npm: "@ai-sdk/openai-compatible",
  // env var NAME the run delivers the auth.json key into — WITHOUT it the key is
  // never wired and opencode fails with "Failed to get the authorization header".
  api_key_env: "MYLLM_API_KEY",
};

test("empty opencode → providers:[provider], model + small_model set", () => {
  const next = applyCustomEndpoint({}, ep);
  const oc = next.opencode as Record<string, unknown>;
  expect(oc.providers).toEqual([provider]);
  expect(oc.small_model).toBe("myllm/my-model");
  expect(next.model).toBe("myllm/my-model");
});

test("missing opencode key entirely → still wires provider + model", () => {
  const next = applyCustomEndpoint({ name: "exp" }, ep);
  const oc = next.opencode as Record<string, unknown>;
  expect(oc.providers).toEqual([provider]);
  expect(oc.small_model).toBe("myllm/my-model");
  expect(next.model).toBe("myllm/my-model");
  expect(next.name).toBe("exp");
});

test("existing providers preserved and appended", () => {
  const existing = {
    id: "other",
    base_url: "http://x/v1",
    models: ["m1"],
    npm: "@ai-sdk/openai-compatible",
  };
  const next = applyCustomEndpoint(
    { opencode: { providers: [existing], small_model: "other/m1" } },
    ep,
  );
  const oc = next.opencode as Record<string, unknown>;
  expect(oc.providers).toEqual([existing, provider]);
  expect(oc.small_model).toBe("myllm/my-model");
  expect(next.model).toBe("myllm/my-model");
});

test("non-array providers treated as empty", () => {
  const next = applyCustomEndpoint(
    { opencode: { providers: "garbage" } },
    ep,
  );
  const oc = next.opencode as Record<string, unknown>;
  expect(oc.providers).toEqual([provider]);
});

test("existing model overwritten", () => {
  const next = applyCustomEndpoint({ model: "anthropic/claude" }, ep);
  expect(next.model).toBe("myllm/my-model");
});

test("wires api_key_env (env NAME, not the secret) and never inlines a key", () => {
  const next = applyCustomEndpoint({}, ep);
  const oc = next.opencode as Record<string, unknown>;
  const prov = (oc.providers as Array<Record<string, unknown>>)[0]!;
  expect(prov.api_key_env).toBe("MYLLM_API_KEY"); // a name, not the secret value
  // the secret itself flows only to auth.json (via writeCreds), never inlined:
  expect(JSON.stringify(next)).not.toContain("apiKey");
  expect(JSON.stringify(next).toLowerCase()).not.toContain("secret");
});

test("derives a sanitized env name from a messy provider id", () => {
  const next = applyCustomEndpoint({}, { ...ep, id: "My-LLM.v2" });
  const prov = ((next.opencode as Record<string, unknown>).providers as
    Array<Record<string, unknown>>)[0]!;
  expect(prov.api_key_env).toBe("MY_LLM_V2_API_KEY");
});
