import { applyCustomEndpoint } from "../src/lib/customEndpoint";

const ep = { id: "myllm", baseUrl: "http://10.0.0.5:8000/v1", model: "my-model" };
const provider = {
  id: "myllm",
  base_url: "http://10.0.0.5:8000/v1",
  models: ["my-model"],
  npm: "@ai-sdk/openai-compatible",
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

test("never writes the raw key into formData/opencode", () => {
  const next = applyCustomEndpoint({}, ep);
  expect(JSON.stringify(next)).not.toContain("api_key");
  expect(JSON.stringify(next).toLowerCase()).not.toContain("secret");
});
