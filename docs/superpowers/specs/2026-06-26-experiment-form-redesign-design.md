# Experiment-form redesign — design

**Date:** 2026-06-26
**Status:** design (approved through brainstorming; pending implementation plan)
**Approach:** evolve the existing rjsf/mui form (not a rewrite).

## Problem

The "new experiment" form is schema-driven (rjsf/mui rendered from the pydantic
JSON schema + `uiSchema.ts`). In its current shape it is hard to use:

- **Deeply nested & flat at once** — every pydantic sub-model becomes a nested
  object block, but there is no information architecture: connection knobs,
  task definition, and the A/B conditions all sit at the same visual level.
- **Long text is unusable** — `task_prompt` / `system_prompt` / inline
  augmentation render as one-line inputs; you cannot read or edit a multi-page
  prompt in them.
- **Conditions are opaque** — the centerpiece of the benchmark (the A/B
  conditions) is just an array of nested objects with no per-condition summary.
- **Free-text where a choice belongs** — `tools` and `orchestration` are typed
  by hand; a typo silently disables the contrast or the controller.
- **No file augmentation from the UI** — today the form deals only in inline
  text: `write_experiment` externalizes `task_prompt`/`system_prompt`/
  `augmentation` to `.md` files and `read_experiment`→`load_experiment` inlines
  them back. You cannot point a condition at an existing host file and confirm
  it resolved.
- **Dead knob on display** — `contract_fields` ("contract aspect-words") is a
  mechanism the user has decided to remove; it should not be in the form at all.
- **Context window is manual** — `model_context_window` must be typed even
  though the vLLM endpoint reports it (`/v1/models` → `max_model_len`).

## Goals

1. Clear top-to-bottom flow: **Basics → Task → Conditions → Run → Advanced**.
2. Long text is editable (compact field + expand-to-modal).
3. Conditions render as compact, readable rows with a focused modal editor.
4. Choices come from dropdowns/multiselects, not free text (tools, orchestration
   methodology, engine).
5. Augmentation supports **Inline text** (today's behavior) or a new **File
   (verified)** mode that points at a host file, with the UI showing which and
   whether the file resolved.
6. Context window auto-loads from the endpoint; manual override still possible.
7. Per-condition **system-prompt override** (global default + override).
8. Per-condition **orchestration engine** (Python | LangGraph).
9. Remove `contract_fields` end-to-end (form + schema + orchestrator).
10. Stay native MUI; visually consistent with the rest of the site.

## Non-goals / deferred

- **Condition presets library** (save/reuse named conditions across
  experiments) — separate spec; the modal editor is the seam it will plug into.
- Reworking the connection/sandbox model — those fields just move to Advanced.
- Touching the run/trace views, metrics, or the orchestrator's forward-only
  semantics (already shipped).

## Section 1 — Information architecture

Render the primary fields under light, labeled groups; push set-once/power-user
fields into a collapsed **Advanced** accordion. Groups and flow:

| Group | Fields |
|---|---|
| **Basics** | `name`, `model` (+ context-window autoload) |
| **Task** | `task_prompt`, `system_prompt` (global default), `target_file`, `target_methods`, `fixture_path`, `reference_path` |
| **Conditions** | `conditions` (rows + modal — Section 2) |
| **Run** | `repetitions`, `verify` |
| **Advanced** (collapsed) | `output_dir`, `timeout_s`, `min_seconds_between_runs`, `rate_limit_retries`, `rate_limit_backoff_s`, `isolation`, `metrics`, `opencode` (providers / sandbox / agent / tools_lib / limits), `orchestration` controller knobs (`target_label`, `max_diagnose_iters`, `no_progress_limit`, `cluster_cap`, `probe_targets`), `overlay_env` |

Implementation: extend `RootObjectFieldTemplate` to render primary fields under
group headers instead of dumping everything, then the Advanced accordion (it
already routes `*` → Advanced; generalize it to a field→group map).

**Removed from the form and schema:** `OrchestrationCfg.contract_fields`.
**Stays hidden (v2 forward-compat, as today):** `isolation.user_field_template`,
`isolation.api_key_env_list`.

## Section 2 — Conditions UX

Conditions are the benchmark's centerpiece, so they get bespoke rendering rather
than the generic array-of-objects widget.

- **List = compact rows.** Each condition is one row showing: name, an
  augmentation chip (`baseline` / `file: <name>` / `inline`), a tools chip
  (e.g. `+impact` or `—`), an orchestration chip (`autonomous` / `phased` /
  `phased+plan` / `phased+graph` / `phased+runtime`), and an engine chip
  (`py` / `langgraph`). Row actions: edit, duplicate, remove. A "+ Add
  condition" button appends a new row (defaults to a baseline).
- **Edit = focused modal.** Clicking a row opens a modal with the full
  per-condition form (Section 3 widgets). This keeps the long augmentation text
  and the per-condition overrides out of the main scroll.
- **Presets** are deferred; the modal is where a future "load/save preset"
  affordance will live.

Implementation: a custom `ConditionsField` (array field replacement) renders the
rows; the modal reuses the rjsf object field for a single `Condition` so the
widgets stay schema-driven.

## Section 3 — Widgets

1. **Augmentation: Inline | File toggle, with verification.**
   - A segmented toggle picks `augmentation_kind` (`text` | `file`); default
     `text` (today's behavior).
   - **Inline mode (default):** a proper multi-line textarea (with the long-text
     expand from widget 4). Stored as `slices/<cond>.md` and round-tripped as
     text exactly as today.
   - **File mode (new):** a path input + a live indicator that calls a verify
     endpoint and shows ✓ `found · <size> · <first line>` or ✗ `not found`. The
     path is stored verbatim (not externalized) and resolved at load time the
     same way `_resolve_text` does (relative to the experiment dir; absolute
     respected) — so the preview matches what the run injects.
   - Empty `augmentation` = baseline (no augmentation), regardless of kind.

2. **Tools multiselect.** Replace the free-text array with a MUI Autocomplete
   multiselect over a curated list (opencode built-ins + the gateable library
   tools, notably `impact`), `freeSolo` so an unknown tool can still be typed.
   Help text states the gating semantics (a tool not listed is disabled for this
   condition — that is what preserves the A/B contrast).

3. **Context-window autoload.** When `model` (and the matching provider
   `base_url`) is set, fetch the endpoint's context window and prefill
   `model_context_window` as a *placeholder/auto* value; the user can override.
   Reuses `model_limits.fetch_context_window`. Surfaced via a small endpoint so
   the browser doesn't talk to the vLLM host directly.

4. **Long-text expand.** A reusable widget for `task_prompt`, `system_prompt`,
   and inline augmentation: a compact multi-line box with an "expand" affordance
   that opens a large modal editor. Same component everywhere.

5. **Orchestration: methodology + engine.**
   - **Methodology** dropdown (`Condition.orchestration` as an enum): `none`
     (autonomous), `phased`, `phased_plan`, `phased_graph`, `phased_runtime`.
   - **Engine** dropdown (`Condition.engine`): `python` | `langgraph`. Default
     `python`.
   - When methodology = `none`, engine is irrelevant (greyed; runner ignores it).
   - `phased_runtime` shows a hint that it needs the experiment-level
     `orchestration.probe_targets` (Advanced).

6. **System prompt (global + override).** The Task group holds the global
   `system_prompt`. Each condition's modal has an optional
   `Condition.system_prompt` override; blank = use the global. The row/modal
   shows whether an override is set.

## Section 4 — Backend schema changes

These pydantic edits drive the schema-driven form (descriptions become help
text) and the runner wiring.

### `abench/config.py`

- **`OrchestrationCfg`:** remove `contract_fields`.
- **`Condition`:** add/changes —
  - `system_prompt: str | None = None` — per-condition override; `None` → global.
  - `engine: Literal["python", "langgraph"] = "python"` — per-condition
    orchestration engine.
  - `orchestration` → `Literal[None, "phased", "phased_plan", "phased_graph",
    "phased_runtime"] = None` (was free `str | None`), so the schema emits an
    enum and the form renders a dropdown.
  - `augmentation_kind: Literal["text", "file"] = "text"`; `augmentation` keeps
    holding the value (inline text when `text` — today's default; a host path
    when `file`).
  - Sharpen `description` on `augmentation`, `overlay`, `tools` (one clear line
    each — they become the form help).

### `abench/orchestrator.py` (drop the aspect-word gate)

- `OrchestratorConfig`: remove `contract_fields` and `min_contract_aspects`.
- `contract_ok`: drop the `hits = sum(... contract_fields ...)` check. The gate
  becomes "contract is non-trivial (length) AND the agent read enough sources".
- `fallback_contract`: drop the `Address: <fields>` clause.
- This is a deliberate behavior change: the UNDERSTAND gate no longer requires
  task-specific keywords — consistent with removing the mechanism. Forward-only
  semantics are unchanged.

### `abench/orchestration_adapters.py`

- `build_orchestrator_config`: stop passing `contract_fields`.

### `abench/runner.py`

- **System prompt:** `system_prompt_eff = build_system_prompt(cond.system_prompt
  or exp.system_prompt, ...)` (currently `exp.system_prompt`, runner.py:511).
- **Engine:** `_select_orchestrator` takes the condition: per-condition
  `cond.engine` wins; `ABENCH_ORCHESTRATOR` env stays as a global fallback;
  default `python`. Resolve it where `_orchestrate = _select_orchestrator()` is
  called (runner.py:531).
- **Augmentation: no runner change.** `compose(exp.task_prompt,
  cond.augmentation)` is unchanged — by the time the runner sees
  `cond.augmentation` it is already resolved text (`load_experiment` /
  `_resolve_text` did it). `augmentation_kind` is consumed by the
  storage/round-trip layer, not the runner.

### `abench_ui/experiments.py` (kind-aware storage round-trip)

This is the real seam for file-vs-text augmentation.

- **`write_experiment`** branches on `augmentation_kind`:
  - `text` → externalize to `slices/<cond>.md` and store that path (today's
    behavior; round-trips as text).
  - `file` → store the user's path **verbatim**; do NOT externalize. (The file
    lives wherever the user put it; the run reads its current content.)
- **`read_experiment`** must round-trip the editor view, so it cannot blindly
  inline file-kind augmentations (that would replace the path with its content
  and lose the file binding on re-edit):
  - `text` → inline the `.md` content (as today).
  - `file` → return the raw path (so the form shows the path + verify indicator).
  - It still uses `load_experiment` for everything else; the augmentation
    handling becomes kind-aware (read the YAML's raw augmentation value for
    file-kind instead of the resolved text).
- Per-condition `system_prompt` override: stored inline in the YAML (optional,
  usually short); not externalized. Experiment-level `system_prompt` keeps its
  `prompts/system.md` externalization.
- `_resolve_text` stays kind-agnostic and lenient (path that exists → read;
  else literal) — the verify endpoint, not a load-time exception, surfaces a
  missing file at edit time.

### New API endpoints (`abench_ui/server.py`)

- **Verify augmentation path** — `POST {name?, path}` → `{found, size, preview}`
  (first line / N bytes). Resolves like `_resolve_text`: relative to the
  experiment dir (`root/name`) when known, absolute respected. For an unsaved
  experiment (no dir yet) it resolves relative to the server cwd / absolute —
  noted as a known edge.
- **Context window** — `POST {model, base_url}` → `{context_window}` via
  `model_limits.fetch_context_window`. Drives widget 3. (If the existing
  `POST /validate/model` can carry this, extend it instead of adding one.)
- **Tools list** is a frontend constant (built-ins + `impact`) + `freeSolo`; no
  endpoint needed.

### Back-compat

- **Inline text is the default** (`augmentation_kind="text"`), which is exactly
  today's behavior — existing UI experiments and the externalize/inline round
  trip are unchanged.
- **YAML/CLI experiments** that reference a slice file in `augmentation` keep
  working: `_resolve_text` reads the file regardless of `kind` (kind only steers
  the UI write/read round-trip, not `load_experiment`'s resolution).
- `Condition.engine`/`system_prompt` default to prior behavior (Python /
  global); `Condition.orchestration` enum still accepts the same string values +
  `None`. Old configs are unaffected.

## Section 5 — UI/UX style

- Native **MUI (rjsf/mui)** throughout; consistent spacing, 0.5px borders,
  spacious-but-quiet layout matching the site.
- Light named group headers (Basics / Task / Conditions / Run) above the
  Advanced accordion.
- One concise line of help under each field (from sharpened `description` +
  `ui:help`).
- Long text → compact box + expand modal; conditions → rows + modal.
- Flow top to bottom: Basics → Task → Conditions → Run → Advanced.

## Affected files (anticipated)

**Backend**
- `abench/config.py` — `Condition` (system_prompt, engine, orchestration enum,
  augmentation_kind, descriptions); `OrchestrationCfg` (drop contract_fields).
- `abench/orchestrator.py` — drop contract_fields / min_contract_aspects;
  `contract_ok`; `fallback_contract`.
- `abench/orchestration_adapters.py` — `build_orchestrator_config`.
- `abench/runner.py` — system-prompt override; per-condition engine selection.
- `abench_ui/experiments.py` — kind-aware `write_experiment`/`read_experiment`.
- `abench_ui/server.py` — verify-path + context-window endpoints.
- (`abench/prompt.py` — unchanged; `compose` stays text-only.)

**Frontend (`web/`)**
- `web/src/schema/uiSchema.ts` — group map; widget bindings; ui:help.
- `web/src/components/ExperimentForm.tsx` — wire new templates/widgets.
- New components: `ConditionsField` (rows), condition modal editor,
  `AugmentationField` (file/inline + verify), `ToolsField` (multiselect),
  `LongTextWidget` (expand), `ContextWindowField` (autoload), orchestration
  methodology/engine selects, `RootObjectFieldTemplate` group rendering.

## Tests

- **Backend:**
  - `write_experiment`/`read_experiment` round-trip: `text` kind externalizes to
    `slices/<cond>.md` and inlines back; `file` kind stores the path verbatim and
    reads back the path (not its content).
  - Runner uses `cond.system_prompt` when set, else `exp.system_prompt`.
  - `_select_orchestrator` resolves per-condition engine (python default,
    langgraph when set, env fallback).
  - `contract_ok` no longer references aspect-words; gate passes/fails on
    length + reads. Update `tests/test_orchestrator.py` fixtures
    (`_CFG`/`_CONTRACT`) and `tests/test_orchestrator_graph_parity.py`
    (drop `contract_fields=[...]` from the constructed `OrchestratorConfig`).
  - Endpoints: verify-path (found/size/preview, missing → not found);
    context-window (parses endpoint, override respected).
- **Frontend:** light render/interaction coverage for the new widgets if a
  harness exists; otherwise manual smoke via the dev server.

## Open questions

- Curated tools list contents — start with opencode built-ins + `impact`; add as
  the registry grows. `freeSolo` covers the rest.
- Whether to fold context-window into the existing model-validation endpoint or
  add a dedicated one — decide at implementation time based on that endpoint's
  current response shape.
