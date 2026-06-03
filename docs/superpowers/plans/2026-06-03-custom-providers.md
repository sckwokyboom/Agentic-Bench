# First-class custom providers + small_model override — Plan

> superpowers:subagent-driven-development. TDD; never weaken tests.

**Goal:** Let an experiment use an OpenAI-compatible / custom endpoint (e.g. `kimi-k2.6`) or any opencode provider, by emitting a `provider` block into the generated `opencode.json` and allowing `small_model` to be overridden. OpenRouter already works (built-in opencode provider); this adds first-class custom/OpenAI-compatible support to the harness + form.

**Decisions:** first-class in abench; make `small_model` overridable (safe default).

**Verified facts:**
- `abench/opencode_client.py:196` builds `config_data = {"$schema", "model", "small_model": self._SMALL_MODEL_FREE (=opencode/mimo-v2.5-free), "agent": {cfg.agent: {prompt, model}}}` and writes it to `<workdir>/opencode.json`. No `provider` block today.
- `RealOpenCodeClient(cfg: OpenCodeCfg, timeout_s)`; constructed as `RealOpenCodeClient(e.opencode, e.timeout_s)`. So new fields belong on `OpenCodeCfg` (`abench/config.py:23`).
- API keys: `AddApiKeyDialog`/`ModelValidationChip` already write `auth.json` keyed by the model's provider PREFIX (`POST /providers/{provider}/credentials` → `~/.local/share/opencode/auth.json` `{<id>:{type:api,key}}`), for ANY id. So a custom `kimi` key is added by typing `model = kimi/kimi-k2.6` and clicking "Add API key" — NO dialog change needed. opencode reads the key from auth.json by provider id; the provider block needs npm+baseURL+models (no secret on disk).
- opencode deep-merges global + workdir-local config; our block sets model/small_model/agent/provider.

---

## Task A — Backend: ProviderCfg + small_model + opencode.json emission
**Files:** `abench/config.py`, `abench/opencode_client.py`; tests `tests/test_config*.py`, `tests/test_opencode_client*.py`.

- `abench/config.py`: add
```python
class ProviderCfg(BaseModel):
    id: str = Field(title="Provider id",
        description="Model prefix for this provider, e.g. 'kimi' → Model 'kimi/kimi-k2.6'. Add its API key via the Model field's 'Add API key' button (stored in opencode auth.json).")
    base_url: str = Field(title="Base URL",
        description="OpenAI-compatible endpoint, e.g. https://host/v1")
    models: list[str] = Field(default_factory=list, title="Model ids",
        description="Model ids this endpoint serves, e.g. kimi-k2.6.")
    npm: str = Field(default="@ai-sdk/openai-compatible", title="SDK package",
        description="opencode provider SDK; the default works for any OpenAI-compatible API.")
    name: str | None = Field(default=None, title="Display name", description="Optional human label.")
    api_key_env: str | None = Field(default=None, title="API key env var",
        description="Optional: read the key from this environment variable instead of opencode auth.json (avoids storing it via the UI).")
```
  Extend `OpenCodeCfg`:
```python
    small_model: str | None = Field(default=None, title="Small model override",
        description="Override opencode's helper model (titles/summaries). Default uses opencode's free native model; set this if you have no opencode-native access, e.g. 'kimi/kimi-k2.6' or 'openrouter/...'.")
    providers: list[ProviderCfg] = Field(default_factory=list, title="Custom providers",
        description="Register OpenAI-compatible / custom endpoints so you can use '<id>/<model>' in Model.")
```
- `abench/opencode_client.py`: in `run_task`, build `small = self._cfg.small_model or self._SMALL_MODEL_FREE`; set `config_data["small_model"] = small`. If `self._cfg.providers`, add:
```python
config_data["provider"] = {}
for p in self._cfg.providers:
    block = {"npm": p.npm, "models": {m: {} for m in p.models}}
    if p.name: block["name"] = p.name
    opts = {"baseURL": p.base_url}
    if p.api_key_env: opts["apiKey"] = "{env:" + p.api_key_env + "}"
    block["options"] = opts
    config_data["provider"][p.id] = block
```
  IMPORTANT: never write a raw secret into opencode.json (the file lands in the workdir). Only `{env:NAME}` or rely on auth.json. (Do NOT add an inline api_key field.)
- Tests: (1) default OpenCodeCfg → config_data has NO `provider` key and `small_model == opencode/mimo-v2.5-free` (unchanged). (2) OpenCodeCfg with a ProviderCfg(id=kimi, base_url, models=[kimi-k2.6], api_key_env=KIMI_API_KEY) + small_model="kimi/kimi-k2.6" → config_data["provider"]["kimi"] == {npm, options:{baseURL, apiKey:"{env:KIMI_API_KEY}"}, models:{"kimi-k2.6":{}}} and config_data["small_model"]=="kimi/kimi-k2.6"; no secret string present. To assert config_data without spawning opencode, refactor the dict-building into a small pure helper `_build_opencode_config(cfg, model, system_prompt) -> dict` and unit-test that (don't run the subprocess). (3) schema test: `Experiment.model_json_schema()` carries the new field descriptions.
- Keep all existing behavior; existing opencode-client tests must stay green.

## Task B — Frontend form polish + smoke + review
**Files:** `web/src/schema/uiSchema.ts` (+ types auto-flow); tests; live smoke.
- The form auto-renders `opencode.small_model` (nullable string → collapseNullable → text field) and `opencode.providers` (array of ProviderCfg objects) under the Advanced → opencode section, with titles/descriptions from the schema. Add uiSchema so the providers array is usable: a clear array title/description and per-item string-array (`models`) item labels suppressed (reuse the `metrics.*.items {ui:options:{label:false}}` pattern). Ensure nullable `small_model`/`name`/`api_key_env` render as plain text (collapseNullable already handles it).
- Build + full suites + tsc.
- Live smoke: seed/edit an experiment with `model: kimi/kimi-k2.6`, `opencode.small_model: kimi/kimi-k2.6`, and a provider {id:kimi, base_url, models:[kimi-k2.6]}; confirm the form renders the provider fields readably; (backend) confirm `_build_opencode_config` produces the right `provider` block. Screenshot the opencode/providers form section.
- Final review.

## Self-review notes
- Secrets never hit opencode.json (env-ref or auth.json only).
- OpenRouter path is unchanged and already works (built-in provider) — document in the answer, no code needed.
- `small_model` default is preserved when unset → no regression for existing experiments.
