# Experiment Form Rework (Workstream A) Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development to implement task-by-task.

**Goal:** Make the experiment-edit form usable — human titles/descriptions, no `anyOf` dropdowns, sensible sections with a collapsible "Advanced", human array/condition labels, and a verify section with a build-system dropdown.

**Approach (user-chosen):** Enrich the rjsf form (keep rjsf + pydantic validation as single source of truth). Field titles/descriptions live in the pydantic models (`Field(title=, description=)`) so they flow into `Experiment.model_json_schema()` → the form AND the CLI/docs. Frontend handles grouping, collapse, labels, and the verify dropdown.

**Tech:** Python pydantic v2; React 18 + TS strict + `noUncheckedIndexedAccess`; @rjsf/mui 5.24 + @mui/material 5.16; Vitest.

**Verified facts:**
- `abench_ui/schema.py` returns `Experiment.model_json_schema()` → `/api/schema` → `loadSchema()` (post-processed in `web/src/api/schemaCache.ts`).
- Experiment model (`abench/config.py`): `name, fixture_path(Path), reference_path(Path), task_prompt, system_prompt, model, output_dir(Path), conditions(list[Condition]), repetitions(int>=1), opencode(OpenCodeCfg{agent,binary}), timeout_s(int), min_seconds_between_runs(float), metrics(MetricsCfg), verify(VerifyCfg), isolation(IsolationCfg), target_file(str|None), target_methods(list[str]|None)`.
- `MetricsCfg`: test_command_patterns[], shell_tool_names[], read_tool_names[], search_tool_names[], command_arg_keys[].
- `VerifyCfg`: command(str|None), enabled(bool), timeout_s(int).
- `IsolationCfg`: nonce_prefix(bool), shuffle_order(bool), user_field_template(str|None, v2/hidden), api_key_env_list(str|None, v2/hidden).
- Current `web/src/schema/uiSchema.ts` already: hides the 2 v2 isolation fields, custom widgets for model/target_methods/augmentation, textarea for system_prompt/user_message, verify.command help+placeholder. NOTE `small_model` uiSchema entry is DEAD (no such model field) — remove it.
- `web/src/api/schemaCache.ts` has `collapseNullableStrings` (string|null only) applied in `loadSchema`.
- `web/src/pages/ExperimentEdit.tsx` renders `<ExperimentForm schema uiSchema widgets ...>` + a read-only `<FixturesPanel>` (already shows detected system + ambiguity).

---

## Task 1: Backend — titles + descriptions on all Experiment fields

**Files:** Modify `abench/config.py`; Test `tests/test_config_schema.py` (create).

- [ ] **Step 1: failing test** `tests/test_config_schema.py`:
```python
from abench.config import Experiment

def test_json_schema_carries_titles_and_descriptions():
    s = Experiment.model_json_schema()
    defs = s.get("$defs", {})
    # top-level field descriptions present
    props = s["properties"]
    assert props["repetitions"].get("description")
    assert props["target_file"].get("description")
    # nested model field descriptions present
    metrics = defs["MetricsCfg"]["properties"]
    assert metrics["test_command_patterns"].get("description")
    assert metrics["command_arg_keys"].get("description")
    verify = defs["VerifyCfg"]["properties"]
    assert verify["command"].get("description")
    iso = defs["IsolationCfg"]["properties"]
    assert iso["nonce_prefix"].get("description")
    assert iso["shuffle_order"].get("description")
```
Run: `.venv/bin/pytest tests/test_config_schema.py -v` → FAIL.

- [ ] **Step 2: add `Field(title=..., description=...)`** to every user-facing field in `Condition`, `OpenCodeCfg`, `MetricsCfg`, `VerifyCfg`, `IsolationCfg`, `Experiment`. RULES: do not change types, defaults, or validation (`ge=1` stays). For fields with `default_factory`, keep it and add `title=/description=` to the same `Field(...)`. For plain-typed fields with a literal default (e.g. `timeout_s: int = 600`), convert to `timeout_s: int = Field(default=600, title="Run timeout (s)", description="...")`. For required fields (e.g. `name: str`), use `name: str = Field(title="Name", description="...")` (no default — pydantic keeps it required). Write concise, accurate, human descriptions, e.g.:
  - `Condition.name`: "Condition label (e.g. baseline, augmented)."
  - `Condition.augmentation`: "Path to the context-slice markdown injected for this condition; null = no augmentation (baseline)."
  - `MetricsCfg.test_command_patterns`: "Regexes matched against tool commands to count test runs (e.g. 'pytest', 'go test')."
  - `MetricsCfg.read_tool_names`/`search_tool_names`/`shell_tool_names`: describe what each classifies.
  - `MetricsCfg.command_arg_keys`: "Tool-arg keys whose value holds the shell command (for matching test_command_patterns)."
  - `VerifyCfg.command`: "Build/test command. Leave blank to auto-detect (gradle/maven/pytest)."
  - `VerifyCfg.enabled`: "Run the build/test verification step after the agent finishes."
  - `VerifyCfg.timeout_s`: "Max seconds for the verify command."
  - `IsolationCfg.nonce_prefix`: "Prepend a unique comment line to the system prompt so each run defeats provider prompt-cache reuse."
  - `IsolationCfg.shuffle_order`: "Randomize condition×repetition execution order to avoid ordering bias."
  - `Experiment.*`: name, fixture_path ("Working tree the agent edits"), reference_path ("Ground-truth tree for comparison"), task_prompt/system_prompt ("inline text or a path to a .md file"), model, output_dir, conditions, repetitions ("Runs per condition"), timeout_s, min_seconds_between_runs ("Throttle between runs to respect provider rate limits"), target_file ("File the target method lives in — optional, for analysis"), target_methods ("Method names under test — optional").
  Keep the v2 isolation fields (`user_field_template`, `api_key_env_list`) as-is (still hidden in the UI) — a description is fine but optional.

- [ ] **Step 3:** Run the new test + the full config/load tests → green. Run the whole Python suite (deselect the 2 env e2e) → still green. Commit.

---

## Task 2: Frontend — generalize the `anyOf` collapse

**Files:** Modify `web/src/api/schemaCache.ts`; Test `web/tests/schemaCache.test.ts`.

- [ ] **Step 1:** Rename/extend `collapseNullableStrings` → `collapseNullable` that collapses ANY `anyOf: [T, {type:"null"}]` (two branches, exactly one being `{type:"null"}`) into the non-null branch T, MERGING the parent node's sibling keys (title/description/default) over the non-null branch's own keys. Concretely: find the non-null branch `nn`; if the other branch is `{type:"null"}` (and only those two), return `{ ...nn, ...rest }` where `rest` is the parent minus `anyOf`. This preserves enum/pattern/format on `nn` AND the parent's description/default. Keep recursion through arrays + object values. Leave 2-branch non-null anyOf (e.g. string+number) and oneOf untouched.
- [ ] **Step 2:** Update `loadSchema` to call `collapseNullable`. Keep `_resetSchemaCache`.
- [ ] **Step 3:** Update/extend `web/tests/schemaCache.test.ts`: keep the string|null cases; ADD: `[{type:"integer"},{type:"null"}]`→`{type:"integer"}`; `[{type:"null"},{type:"integer"}]` (reverse)→`{type:"integer"}`; a nullable branch carrying `enum`/`description` keeps them; non-nullable `[string,number]` unchanged. Run → green; `npx tsc -b` clean. Commit.

---

## Task 3: Frontend — sections, Advanced accordion, human array/condition labels, verify dropdown

**Files:** Modify `web/src/schema/uiSchema.ts`, `web/src/schema/widgets.tsx`, `web/src/pages/ExperimentEdit.tsx`; Create `web/src/schema/RootObjectFieldTemplate.tsx`, `web/src/schema/ConditionItemTemplate.tsx`, `web/src/components/VerifyField.tsx`; Tests `web/tests/VerifyField.test.tsx`, `web/tests/ExperimentForm.sections.test.tsx`.

**3a — Sections + Advanced.** Create a custom root `ObjectFieldTemplate` (`RootObjectFieldTemplate.tsx`) used ONLY for the root object: it receives `properties` (array of `{ name, content }`). Partition by a constant `ADVANCED = new Set(["metrics","isolation","opencode","timeout_s","min_seconds_between_runs","output_dir","target_file","target_methods","fixture_path","reference_path"])`. Render non-advanced props in document order first, then a collapsible MUI `<Accordion>` titled "Advanced (metrics, isolation, paths, tuning)" containing the advanced props. (Core stays: name, model, task_prompt, system_prompt, conditions, repetitions, verify.) Register it via the Form `templates={{ ObjectFieldTemplate: RootObjectFieldTemplate }}` BUT guard so it only special-cases the root (detect root by `props.idSchema.$id === "root"`); for non-root objects, fall back to the default `ObjectFieldTemplate` (import `getDefaultRegistry` or render the default template from `props.registry.templates.ObjectFieldTemplate` when not root). Add `templates` prop passthrough to `ExperimentForm`.

**3b — Condition item labels.** Provide a custom `ArrayFieldItemTemplate` (or use `ui:options`/`ArrayFieldTemplate`) for the `conditions` array so each item is titled by its `name` value (e.g. "Condition: baseline") instead of the index. Wire via uiSchema `conditions: { "ui:ArrayFieldItemTemplate": ... }` or a dedicated template. Keep add/remove working. (If per-item titling via template is impractical in rjsf 5.24, set the conditions array `ui:title`/`ui:description` and ensure each item clearly shows its `name` field at top — acceptable fallback, but prefer the name-titled item.)

**3c — Verify build-system dropdown.** Create `VerifyField.tsx` registered as a custom field for the `verify` object via uiSchema `verify: { "ui:field": "VerifyField" }` (register in the Form `fields={{ VerifyField }}`). It renders:
  - A MUI `Select` "Build system" with options: `auto` (→ command=null, autodetect), `gradle` (→ `gradle test`), `maven` (→ `mvn test`), `pytest` (→ `pytest`), `custom` (reveal a text field for an arbitrary command).
  - Derive the current selection from `formData.command`: null/empty→auto; exact match to a canonical→that system; otherwise→custom (and show the text field pre-filled).
  - A text field (shown only for `custom`) bound to `command`.
  - The `enabled` switch and `timeout_s` number field.
  - On change, call `onChange` with the updated `verify` object `{command, enabled, timeout_s}`.
  - Use `props.formData`, `props.onChange`, `props.schema`. Keep it controlled. Respect `noUncheckedIndexedAccess`.
  Optionally surface the detected system: ExperimentEdit can pass `detected.data` into the form via `formContext={{ detectedVerify: detected.data }}`; VerifyField reads `props.formContext?.detectedVerify` to show "(auto-detected: gradle)" next to the auto option. (Nice-to-have; the FixturesPanel already shows ambiguity, so this is optional.)

**3d — uiSchema cleanup + order.** Remove the dead `small_model` entry. Add `ui:order` on the root to put core fields first (`["name","model","task_prompt","system_prompt","conditions","repetitions","verify","*"]`). Keep existing widgets (model, target_methods, augmentation, textareas). Ensure array fields (test_command_patterns etc.) now show their schema title/description (from Task 1) — no extra work if titles flow; optionally set items `ui:options: { } ` for cleaner rows.

- [ ] **Step 1 (TDD):** `web/tests/VerifyField.test.tsx` — render the verify field standalone (mock rjsf field props): selecting "gradle" calls onChange with `command: "gradle test"`; "auto" → `command: null`; "custom" reveals a text field and typing sets `command`; a preset command like `./gradlew check` shows as "custom" with the text pre-filled. `web/tests/ExperimentForm.sections.test.tsx` — render `ExperimentForm` with the real schema (or a representative subset) + uiSchema + templates/fields, assert: an "Advanced" accordion is present; `metrics`/`isolation` fields are inside it (collapsed by default — query that the Advanced summary exists and core fields like the `name` input are visible at top); no `combobox`/`select` exists for `verify.command` itself (it's the system Select + conditional text, not an anyOf picker). Make tests meaningful, not tautological. Run → fail.
- [ ] **Step 2:** Implement 3a–3d. Run the new tests + the full frontend suite → green. `npx tsc -b` → clean. Commit.

---

## Task 4: Integration — build, suites, boot/render smoke

**Files:** none (verification).

- [ ] Frontend: `npm test -- --run` (all green), `npx tsc -b` (clean), `npm run build` (succeeds).
- [ ] Python: full suite minus the 2 env e2e → green.
- [ ] Boot smoke: `abench-ui --experiments-dir <seeded>` with an experiment that has a gradle+pom fixture; open `/experiments/<name>`; confirm via preview_eval: (a) field descriptions render (help text present), (b) an "Advanced" accordion exists and metrics/isolation live inside it, (c) the verify section shows the build-system Select (auto/gradle/maven/pytest/custom), not an anyOf dropdown, (d) conditions are labeled by name, (e) no `*-0 *` bare array index labels remain as the only label (arrays now have human titles/descriptions). Screenshot.
- [ ] Final commit if smoke fixes needed.

---

## Self-review notes
- Single source of truth: descriptions in pydantic → schema → form + CLI. No duplicated help text in the frontend.
- The verify dropdown is pure UI sugar over the single `verify.command` field (no backend schema change) — `auto`=null, known systems=canonical command, `custom`=free text. Autodetect + ambiguity warning (FixturesPanel) are unchanged.
- Validation stays with rjsf/pydantic; custom field/templates must not break `validateFormData`.
- Old experiments still load: added Field metadata doesn't change parsing; the form reads the same `formData` shape.
