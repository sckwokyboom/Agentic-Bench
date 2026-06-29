# Experiment-form redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the schema-driven experiment form usable — clear Basics→Task→Conditions→Run→Advanced flow, conditions as rows + a focused editor, real dropdowns, file-or-inline augmentation with verification, context-window autoload, and per-condition system-prompt/engine — while removing the dead `contract_fields` mechanism.

**Architecture:** Backend pydantic edits (`abench/config.py`) drive the rjsf/mui form via `/api/schema`; the orchestrator drops the aspect-word gate; storage round-trip (`abench_ui/experiments.py`) becomes augmentation-kind-aware; two small endpoints back the new widgets; the frontend evolves the existing rjsf form with custom widgets/fields/templates plus a bespoke conditions editor.

**Tech Stack:** Python 3.11 / pydantic v2 / FastAPI / pytest (backend); React + TypeScript + Vite + MUI + `@rjsf/mui` (frontend). Backend uses TDD (pytest). The frontend has **no test harness**, so frontend tasks gate on `npm run build` (which runs `tsc -b`) plus a stated manual smoke check.

---

## File structure

**Backend (modify):**
- `abench/orchestrator.py` — drop `contract_fields`/`min_contract_aspects`; simplify `contract_ok`, `fallback_contract`.
- `abench/config.py` — `Condition` new fields + `orchestration` enum; drop `OrchestrationCfg.contract_fields`; sharpen descriptions.
- `abench/orchestration_adapters.py` — `build_orchestrator_config` stops passing `contract_fields`.
- `abench/runner.py` — per-condition system-prompt override + per-condition engine selection.
- `abench_ui/experiments.py` — `write_experiment`/`read_experiment` augmentation-kind-aware.
- `abench_ui/server.py` — `POST /api/augmentation/verify`, `POST /api/model/context`.

**Backend (tests):** `tests/test_orchestrator.py`, `tests/test_orchestrator_graph_parity.py`, `tests/test_robustness.py` (existing, edited); new `tests/abench_ui/test_experiments_roundtrip.py`, `tests/abench_ui/test_form_support_api.py`.

**Frontend (create):**
- `web/src/schema/registry.ts` — central widget/field/template registry (DRY).
- `web/src/components/LongTextField.tsx` — compact textarea + expand-to-modal.
- `web/src/components/ContextWindowField.tsx` — autoload from endpoint.
- `web/src/components/ToolsSelect.tsx`, `OrchestrationSelect.tsx`, `EngineSelect.tsx` — condition sub-controls.
- `web/src/components/ConditionModal.tsx`, `ConditionsField.tsx` — rows + editor.

**Frontend (modify):** `web/src/components/AugmentationField.tsx` (inline/file + verify), `web/src/schema/widgets.tsx`, `web/src/schema/uiSchema.ts`, `web/src/schema/RootObjectFieldTemplate.tsx`, `web/src/pages/ExperimentEdit.tsx`, `web/src/api/types.ts`, `web/src/api/queries.ts`.

---

## Task 1: Remove the contract aspect-word mechanism

Removing `contract_fields` from `OrchestratorConfig` and from `OrchestrationCfg` must land together (the adapter passes one into the other), so this is one green commit. The UNDERSTAND gate keeps only "non-trivial contract + enough reads".

**Files:**
- Modify: `abench/orchestrator.py:58-69` (`OrchestratorConfig`), `:77-86` (`contract_ok`), `:136-139` (`fallback_contract`)
- Modify: `abench/config.py:380-409` (`OrchestrationCfg`)
- Modify: `abench/orchestration_adapters.py:194-206` (`build_orchestrator_config`)
- Test: `tests/test_orchestrator.py:15,20-37`, `tests/test_orchestrator_graph_parity.py:82`

- [ ] **Step 1: Update the orchestrator tests to the new behavior (red)**

In `tests/test_orchestrator.py`, change the fixture on line 15:

```python
_CFG = OrchestratorConfig(min_understand_reads=2)
```

Replace the two aspect tests (lines 20-31) with one that asserts a prose contract with enough reads now PASSES (aspect-words no longer gate):

```python
def test_contract_ok_requires_only_substance_and_reads():
    good = PhaseOutcome(_trace_with_reads(2),
                        "Contract: handles WRAP and SPAN overflow with indent.")
    assert contract_ok(good, _CFG)[0] is True


def test_contract_ok_accepts_prose_without_keywords():
    # The aspect-word gate is gone: substantive prose + enough reads is enough.
    ok = PhaseOutcome(_trace_with_reads(3),
                      "This describes the method behavior in plain prose only, at length.")
    assert contract_ok(ok, _CFG)[0] is True
```

Leave `test_contract_rejected_when_not_enough_reads` (lines 33-37) unchanged — the reads gate stays.

- [ ] **Step 2: Update the parity test fixture**

In `tests/test_orchestrator_graph_parity.py:82`, drop `contract_fields`:

```python
    cfg = OrchestratorConfig(min_understand_reads=2, with_plan=True)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_orchestrator.py -q`
Expected: FAIL — `OrchestratorConfig.__init__() got an unexpected keyword argument 'contract_fields'` is NOT yet raised (the field still exists), but `test_contract_ok_accepts_prose_without_keywords` FAILS because `contract_ok` still rejects on too-few aspects.

- [ ] **Step 4: Simplify `OrchestratorConfig`**

In `abench/orchestrator.py`, replace the dataclass body (lines 58-69):

```python
@dataclass
class OrchestratorConfig:
    # Task-specific scaffolding (supplied per experiment, NOT hardcoded):
    target_label: str = "the target method"
    # Generic knobs:
    with_plan: bool = False
    min_understand_reads: int = 2
    max_diagnose_iters: int = 8
    no_progress_limit: int = 2
    cluster_cap: int = 5
```

- [ ] **Step 5: Simplify `contract_ok`**

Replace `contract_ok` (lines 77-86):

```python
def contract_ok(outcome: PhaseOutcome, cfg: OrchestratorConfig) -> tuple[bool, str]:
    text = (outcome.text or "").strip()
    if len(text) < 40:
        return False, "contract is empty / too short"
    if _count_reads(outcome.trace) < cfg.min_understand_reads:
        return False, "did not read enough sources (callers/tests)"
    return True, "ok"
```

- [ ] **Step 6: Simplify `fallback_contract`**

Replace `fallback_contract` (lines 136-139):

```python
def fallback_contract(failures: list[TestFailure], cfg: OrchestratorConfig) -> str:
    names = ", ".join(sorted({f.classname.rsplit('.', 1)[-1] for f in failures})[:8])
    return (f"[auto] Contract for {cfg.target_label}, derived from failing tests: "
            f"satisfy {names}.")
```

- [ ] **Step 7: Drop `contract_fields` from `OrchestrationCfg`**

In `abench/config.py`, delete the `contract_fields` Field (lines 383-390) so `OrchestrationCfg` begins:

```python
class OrchestrationCfg(BaseModel):
    """Experiment-level scaffolding for phased-orchestration conditions. Generic
    knobs + per-task scaffolding live here so the orchestrator stays task-agnostic."""
    target_label: str = Field(
        default="the target method",
        title="Target label",
        description="Human label for the method under repair, used in phase prompts.",
    )
```

- [ ] **Step 8: Drop `contract_fields` from the adapter**

In `abench/orchestration_adapters.py`, replace `build_orchestrator_config` (lines 194-206):

```python
def build_orchestrator_config(orch_cfg, mode: str) -> OrchestratorConfig:
    """OrchestratorConfig from the experiment's orchestration block + the
    condition's mode ('phased' | 'phased_plan' | ...)."""
    return OrchestratorConfig(
        target_label=orch_cfg.target_label,
        with_plan=(mode == "phased_plan"),
        max_diagnose_iters=orch_cfg.max_diagnose_iters,
        no_progress_limit=orch_cfg.no_progress_limit,
        cluster_cap=orch_cfg.cluster_cap,
    )
```

- [ ] **Step 9: Run the full orchestrator + parity + robustness suites (green)**

Run: `python3 -m pytest tests/test_orchestrator.py tests/test_orchestrator_graph_parity.py tests/test_robustness.py -q`
Expected: PASS (parity skips cleanly if `langgraph` isn't installed).

- [ ] **Step 10: Grep for stragglers**

Run: `grep -rn "contract_fields\|min_contract_aspects" abench/ tests/`
Expected: no matches.

- [ ] **Step 11: Commit**

```bash
git add abench/orchestrator.py abench/config.py abench/orchestration_adapters.py tests/test_orchestrator.py tests/test_orchestrator_graph_parity.py
git commit -m "refactor(orchestrator): drop the contract aspect-word gate"
```

---

## Task 2: Condition schema fields + orchestration enum

Add `augmentation_kind`, `engine`, `system_prompt` and turn `orchestration` into an enum so the form renders dropdowns. Descriptions become the form's help text.

**Files:**
- Modify: `abench/config.py:23-68` (`Condition`)
- Test: `tests/abench_ui/test_schema.py` (add a field-presence assertion)

- [ ] **Step 1: Write a schema test (red)**

Append to `tests/abench_ui/test_schema.py`:

```python
def test_condition_schema_exposes_new_fields():
    from abench_ui.schema import experiment_json_schema
    s = experiment_json_schema()
    cond = s["$defs"]["Condition"]["properties"]
    assert set(cond) >= {
        "name", "augmentation", "augmentation_kind", "overlay", "tools",
        "orchestration", "engine", "system_prompt",
    }
    # orchestration is now an enum (nullable), not a free string
    orch = cond["orchestration"]
    flat = orch.get("enum") or [b.get("const") for b in orch.get("anyOf", []) if "const" in b]
    # pydantic emits Literal members; tolerate either enum or anyOf-const shape
    assert "phased_runtime" in (flat or [])
    assert cond["engine"]["default"] == "python"
    assert cond["augmentation_kind"]["default"] == "text"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest tests/abench_ui/test_schema.py::test_condition_schema_exposes_new_fields -q`
Expected: FAIL with `KeyError: 'augmentation_kind'`.

- [ ] **Step 3: Rewrite `Condition`**

In `abench/config.py`, replace the whole `Condition` class (lines 23-68):

```python
class Condition(BaseModel):
    name: str = Field(
        title="Name",
        description="Condition label (e.g. baseline, augmented).",
    )
    augmentation: str | None = Field(
        default=None,
        title="Augmentation",
        description=(
            "Extra context injected for this condition. Blank = no augmentation "
            "(baseline). See augmentation_kind for inline-text vs file."
        ),
    )
    augmentation_kind: Literal["text", "file"] = Field(
        default="text",
        title="Augmentation kind",
        description=(
            "'text' = inline markdown (stored as slices/<name>.md); 'file' = a "
            "path to an existing file whose contents are injected at run time."
        ),
    )
    overlay: str | None = Field(
        default=None,
        title="Overlay",
        description=(
            "Directory copied into the run workdir before the seed commit "
            "(per-session tool files); blank = none. '*.tmpl' files are "
            "rendered with overlay_env and written without the suffix."
        ),
    )
    tools: list[str] = Field(
        default_factory=list,
        title="Enabled tools",
        description=(
            "OpenCode tool names this condition enables (e.g. ['impact']). A tool "
            "shipped by opencode.tools_lib that is NOT listed is disabled for this "
            "condition — so baseline (no tools) never sees it, preserving the A/B "
            "contrast."
        ),
    )
    orchestration: Literal[
        "phased", "phased_plan", "phased_graph", "phased_runtime"
    ] | None = Field(
        default=None,
        title="Orchestration mode",
        description=(
            "None = autonomous opencode loop (baseline). 'phased' = forced "
            "UNDERSTAND→IMPLEMENT→DIAGNOSE controller; 'phased_plan' adds PLAN; "
            "'phased_graph' focuses DIAGNOSE on the target's call-graph blast "
            "radius; 'phased_runtime' injects a runtime diagnostic card (actual "
            "args + call corridor + throw) into DIAGNOSE. Requires the "
            "experiment-level orchestration block (and probe_targets for "
            "phased_runtime)."
        ),
    )
    engine: Literal["python", "langgraph"] = Field(
        default="python",
        title="Orchestration engine",
        description=(
            "Phased-controller implementation: 'python' (default) or 'langgraph' "
            "(parity build). Ignored when orchestration is None. The "
            "ABENCH_ORCHESTRATOR env var, if set, overrides this globally."
        ),
    )
    system_prompt: str | None = Field(
        default=None,
        title="System prompt override",
        description=(
            "Per-condition system prompt; blank = use the experiment-level "
            "system prompt."
        ),
    )
```

- [ ] **Step 4: Run the schema test (green)**

Run: `python3 -m pytest tests/abench_ui/test_schema.py -q`
Expected: PASS.

- [ ] **Step 5: Sanity-check existing config load still works**

Run: `python3 -m pytest tests/test_config.py tests/abench_ui/test_experiments.py -q`
Expected: PASS (existing YAML uses the same `orchestration` string values + `None`).

- [ ] **Step 6: Commit**

```bash
git add abench/config.py tests/abench_ui/test_schema.py
git commit -m "feat(config): per-condition augmentation_kind, engine, system_prompt; orchestration enum"
```

---

## Task 3: Runner — per-condition system-prompt override + engine selection

**Files:**
- Modify: `abench/runner.py:96-104` (`_select_orchestrator`), `:488`, `:511-516` (system prompt), `:531` (call site)
- Test: `tests/test_runner_orchestration_select.py` (create)

- [ ] **Step 1: Write the failing tests (red)**

Create `tests/test_runner_orchestration_select.py`:

```python
import types
from abench.config import Condition
from abench.runner import _select_orchestrator
from abench.prompt import build_system_prompt


def _cond(**kw):
    return Condition(name="c", **kw)


def test_engine_defaults_to_python(monkeypatch):
    monkeypatch.delenv("ABENCH_ORCHESTRATOR", raising=False)
    fn = _select_orchestrator(_cond())
    assert fn.__name__ == "run"           # abench.orchestrator.run


def test_env_overrides_condition_engine(monkeypatch):
    monkeypatch.setenv("ABENCH_ORCHESTRATOR", "langgraph")
    import pytest
    pytest.importorskip("langgraph")
    fn = _select_orchestrator(_cond(engine="python"))
    assert fn.__name__ == "run_graph"     # env is the global override


def test_condition_engine_langgraph(monkeypatch):
    monkeypatch.delenv("ABENCH_ORCHESTRATOR", raising=False)
    import pytest
    pytest.importorskip("langgraph")
    fn = _select_orchestrator(_cond(engine="langgraph"))
    assert fn.__name__ == "run_graph"


def test_system_prompt_override_precedence():
    # cond override wins; blank falls back to the experiment prompt.
    assert build_system_prompt("OVR", forbid_external_sources=False) == "OVR"
    assert build_system_prompt("BASE", forbid_external_sources=False) == "BASE"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_runner_orchestration_select.py -q`
Expected: FAIL — `_select_orchestrator() takes 0 positional arguments but 1 was given`.

- [ ] **Step 3: Make `_select_orchestrator` condition-aware**

In `abench/runner.py`, replace `_select_orchestrator` (lines 96-104):

```python
def _select_orchestrator(cond=None):
    """Pick the phased orchestrator implementation. Precedence: the
    ABENCH_ORCHESTRATOR env var (global override, back-compat) wins; else the
    condition's `engine`; default the Python run(). Lazy imports so the default
    path doesn't require langgraph."""
    engine = (os.environ.get("ABENCH_ORCHESTRATOR")
              or getattr(cond, "engine", None) or "python")
    if engine == "langgraph":
        from .orchestrator_graph import run_graph
        return run_graph
    from .orchestrator import run as _run_py
    return _run_py
```

- [ ] **Step 4: Pass the condition at the call site**

In `abench/runner.py:531`, change:

```python
                    _orchestrate = _select_orchestrator(cond)   # env override | per-condition engine | python
```

- [ ] **Step 5: Apply the per-condition system-prompt override**

In `abench/runner.py`, line 488, change the pre-loop default:

```python
        system_prompt_eff = cond.system_prompt or exp.system_prompt
```

And in the per-attempt rebuild (line 511-512), change the base argument:

```python
                system_prompt_eff = build_system_prompt(
                    cond.system_prompt or exp.system_prompt,
                    nonce=nonce,
                    fixture_sha=sha,
                    forbid_external_sources=exp.isolation.forbid_external_sources,
                )
```

- [ ] **Step 6: Run the new tests + the robustness suite (green)**

Run: `python3 -m pytest tests/test_runner_orchestration_select.py tests/test_robustness.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add abench/runner.py tests/test_runner_orchestration_select.py
git commit -m "feat(runner): per-condition system-prompt override + engine selection"
```

---

## Task 4: Storage round-trip — augmentation-kind-aware write/read

`text`-kind augmentation keeps today's externalize-to-`slices/<name>.md` behavior; `file`-kind stores the path verbatim and reads back the path (not its content) so the editor shows the file binding.

**Files:**
- Modify: `abench_ui/experiments.py:56-64` (`read_experiment`), `:97-103` (write loop)
- Test: `tests/abench_ui/test_experiments_roundtrip.py` (create)

- [ ] **Step 1: Write the failing round-trip tests (red)**

Create `tests/abench_ui/test_experiments_roundtrip.py`:

```python
from pathlib import Path
from abench_ui.experiments import write_experiment, read_experiment


def _base_payload(root: Path, conditions):
    (root / "stripped").mkdir(parents=True, exist_ok=True)
    (root / "stripped" / "a.py").write_text("x")
    (root / "original").mkdir(parents=True, exist_ok=True)
    return {
        "name": "exp", "fixture_path": str(root / "stripped"),
        "reference_path": str(root / "original"), "task_prompt": "do it",
        "system_prompt": "be careful", "model": "opencode/m",
        "output_dir": str(root / "runs"), "repetitions": 1,
        "conditions": conditions,
    }


def test_text_kind_externalizes_and_inlines_back(tmp_path):
    payload = _base_payload(tmp_path, [
        {"name": "aug", "augmentation": "INLINE SLICE TEXT", "augmentation_kind": "text"},
    ])
    write_experiment(tmp_path, "exp", payload)
    assert (tmp_path / "exp" / "slices" / "aug.md").read_text() == "INLINE SLICE TEXT"
    out = read_experiment(tmp_path, "exp")
    cond = out["conditions"][0]
    assert cond["augmentation"] == "INLINE SLICE TEXT"   # inlined back
    assert cond["augmentation_kind"] == "text"


def test_file_kind_stores_path_verbatim_and_reads_path_back(tmp_path):
    slice_file = tmp_path / "external" / "slice.md"
    slice_file.parent.mkdir(parents=True)
    slice_file.write_text("FILE SLICE CONTENT")
    payload = _base_payload(tmp_path, [
        {"name": "aug", "augmentation": str(slice_file), "augmentation_kind": "file"},
    ])
    write_experiment(tmp_path, "exp", payload)
    # NOT externalized to slices/
    assert not (tmp_path / "exp" / "slices" / "aug.md").exists()
    out = read_experiment(tmp_path, "exp")
    cond = out["conditions"][0]
    assert cond["augmentation"] == str(slice_file)       # path, not content
    assert cond["augmentation_kind"] == "file"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/abench_ui/test_experiments_roundtrip.py -q`
Expected: FAIL — `test_file_kind...` fails because the file is externalized and read back as content.

- [ ] **Step 3: Make the write loop kind-aware**

In `abench_ui/experiments.py`, replace the augmentation loop (lines 97-103):

```python
    for cond in conditions:
        aug = cond.get("augmentation")
        if aug is None:
            continue
        # File-kind augmentation is a path the user manages → store verbatim,
        # do NOT externalize. Text-kind is inline markdown → slices/<name>.md.
        if cond.get("augmentation_kind") == "file":
            continue
        slice_path = f"./{_SLICES_DIR}/{cond['name']}.md"
        _atomic_write(exp_dir / _SLICES_DIR / f"{cond['name']}.md", aug)
        cond["augmentation"] = slice_path
```

- [ ] **Step 4: Make `read_experiment` round-trip file-kind paths**

In `abench_ui/experiments.py`, replace `read_experiment` (lines 56-64):

```python
def read_experiment(root: Path, name: str) -> dict:
    """Return the Experiment payload for the editor. Text fields are inlined; a
    file-kind augmentation is returned as its PATH (not its resolved content) so
    the editor shows the file binding rather than an inlined blob."""
    yaml_path = Path(root) / name / "experiment.yaml"
    if not yaml_path.is_file():
        raise ExperimentNotFound(name)
    exp = load_experiment(yaml_path)
    data = exp.model_dump(mode="json")
    raw = yaml.safe_load(yaml_path.read_text()) or {}
    raw_by_name = {c.get("name"): c for c in raw.get("conditions", [])
                   if isinstance(c, dict)}
    for cond in data.get("conditions", []):
        if cond.get("augmentation_kind") == "file":
            rc = raw_by_name.get(cond.get("name"))
            if rc is not None:
                cond["augmentation"] = rc.get("augmentation")
    return data
```

(`yaml` is already imported at the top of the module — it backs `yaml.safe_dump`.)

- [ ] **Step 5: Run the round-trip + existing experiments tests (green)**

Run: `python3 -m pytest tests/abench_ui/test_experiments_roundtrip.py tests/abench_ui/test_experiments.py tests/abench_ui/test_experiments_api.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add abench_ui/experiments.py tests/abench_ui/test_experiments_roundtrip.py
git commit -m "feat(ui-storage): augmentation-kind-aware write/read round-trip"
```

---

## Task 5: Form-support endpoints — verify augmentation path + model context

**Files:**
- Modify: `abench_ui/server.py:42-70` (body models), routes near `:448` (`/validate/model`)
- Test: `tests/abench_ui/test_form_support_api.py` (create)

- [ ] **Step 1: Write the failing endpoint tests (red)**

Create `tests/abench_ui/test_form_support_api.py`:

```python
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from abench_ui.server import create_app


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(experiments_dir=tmp_path)), tmp_path


def test_verify_augmentation_found_absolute(client):
    c, tmp = client
    f = tmp / "slice.md"
    f.write_text("first line\nsecond line\n")
    r = c.post("/api/augmentation/verify", json={"path": str(f)})
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is True
    assert body["size"] == f.stat().st_size
    assert body["preview"].startswith("first line")


def test_verify_augmentation_missing(client):
    c, _ = client
    r = c.post("/api/augmentation/verify", json={"path": "/no/such/file.md"})
    assert r.status_code == 200
    assert r.json()["found"] is False


def test_model_context_returns_window(client, monkeypatch):
    c, _ = client
    import abench_ui.server as srv
    monkeypatch.setattr(srv, "fetch_context_window", lambda *a, **k: 131072)
    r = c.post("/api/model/context",
               json={"model": "vllm/qwen", "base_url": "http://h/v1"})
    assert r.status_code == 200
    assert r.json()["context_window"] == 131072


def test_model_context_none_on_failure(client, monkeypatch):
    c, _ = client
    import abench_ui.server as srv
    monkeypatch.setattr(srv, "fetch_context_window", lambda *a, **k: None)
    r = c.post("/api/model/context", json={"model": "m", "base_url": ""})
    assert r.json()["context_window"] is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/abench_ui/test_form_support_api.py -q`
Expected: FAIL — 404 (routes don't exist).

- [ ] **Step 3: Add the request body models + the import**

In `abench_ui/server.py`, add near the top imports (after line 27's `from abench.config import Experiment`):

```python
from abench.model_limits import fetch_context_window
```

Add after `_VerifyStartBody` (line 70):

```python
class _VerifyAugBody(BaseModel):
    path: str
    name: str | None = None      # resolve relative to this experiment's dir if given


class _ModelContextBody(BaseModel):
    model: str
    base_url: str
    api_key_env: str | None = None
```

- [ ] **Step 4: Add the routes**

In `abench_ui/server.py`, add just before the `@api.post("/validate/model")` route (line 448):

```python
    @api.post("/augmentation/verify")
    def _verify_augmentation(body: _VerifyAugBody):
        """Resolve an augmentation FILE path the way load_experiment does (base =
        the experiment dir when known; absolute paths respected) and report
        whether it exists, its size, and a short preview."""
        base = Path.cwd()
        if body.name:
            cand = state["experiments_dir"].resolve() / body.name
            if cand.is_dir():
                base = cand
        target = (base / body.path)          # absolute body.path overrides base
        if not target.is_file():
            return {"found": False, "size": 0, "preview": ""}
        size = target.stat().st_size
        head = target.read_text("utf-8", "replace")[:200]
        return {"found": True, "size": size, "preview": head}

    @api.post("/model/context")
    def _model_context(body: _ModelContextBody):
        """Best-effort: the model's context window from its /v1/models endpoint.
        Returns {context_window: int|None} — None on any failure (the UI falls
        back to a manual value)."""
        import os
        api_key = os.environ.get(body.api_key_env) if body.api_key_env else None
        return {"context_window": fetch_context_window(
            body.base_url, api_key, body.model)}
```

- [ ] **Step 5: Run the endpoint tests (green)**

Run: `python3 -m pytest tests/abench_ui/test_form_support_api.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add abench_ui/server.py tests/abench_ui/test_form_support_api.py
git commit -m "feat(ui-api): augmentation path verify + model context-window endpoints"
```

---

## Task 6: Frontend — central registry + typed API helpers

DRY: pull the inline widget/field/template maps out of `ExperimentEdit.tsx` into one module, and add typed client calls for the two new endpoints. No behavior change yet (refactor + additions).

**Files:**
- Create: `web/src/schema/registry.ts`
- Modify: `web/src/api/types.ts`, `web/src/api/queries.ts`, `web/src/pages/ExperimentEdit.tsx:25-37,164-166`

- [ ] **Step 1: Add API response types**

Append to `web/src/api/types.ts`:

```typescript
export interface VerifyAugmentationResp {
  found: boolean;
  size: number;
  preview: string;
}

export interface ModelContextResp {
  context_window: number | null;
}
```

- [ ] **Step 2: Add client helpers**

`queries.ts` already imports `apiPostJson` from `./client` and the types namespace as `import * as t from "./types"`, so no new imports are needed. Append these two functions to the end of `web/src/api/queries.ts`:

```typescript
export async function verifyAugmentation(
  path: string, name?: string,
): Promise<t.VerifyAugmentationResp> {
  return apiPostJson<t.VerifyAugmentationResp>("/api/augmentation/verify", { path, name });
}

export async function fetchModelContext(
  model: string, baseUrl: string, apiKeyEnv?: string | null,
): Promise<t.ModelContextResp> {
  return apiPostJson<t.ModelContextResp>("/api/model/context", {
    model, base_url: baseUrl, api_key_env: apiKeyEnv ?? null,
  });
}
```

- [ ] **Step 3: Create the registry module**

Create `web/src/schema/registry.ts`:

```typescript
import {
  ModelValidationWidget, TargetMethodsWidget, AugmentationWidget,
} from "./widgets";
import RootObjectFieldTemplate from "./RootObjectFieldTemplate";
import DescriptionFieldTemplate from "./DescriptionFieldTemplate";
import VerifyField from "../components/VerifyField";

export const customWidgets = {
  ModelValidationWidget, TargetMethodsWidget, AugmentationWidget,
};
export const customFields = { VerifyField };
export const customTemplates = {
  ObjectFieldTemplate: RootObjectFieldTemplate,
  DescriptionFieldTemplate,
};
```

- [ ] **Step 4: Use the registry in ExperimentEdit**

In `web/src/pages/ExperimentEdit.tsx`, delete the inline imports + maps (lines 25-37) and import from the registry instead:

```typescript
import { uiSchema } from "../schema/uiSchema";
import { customWidgets, customFields, customTemplates } from "../schema/registry";
```

(Leave the `<ExperimentForm … widgets={customWidgets} fields={customFields} templates={customTemplates} />` usage at lines 164-166 unchanged.)

- [ ] **Step 5: Typecheck + build**

Run: `cd web && npm run build`
Expected: build succeeds (no TS errors).

- [ ] **Step 6: Commit**

```bash
git add web/src/schema/registry.ts web/src/api/types.ts web/src/api/queries.ts web/src/pages/ExperimentEdit.tsx
git commit -m "refactor(web): central rjsf registry + typed form-support API helpers"
```

---

## Task 7: Frontend — LongTextField (compact + expand)

A reusable widget for long prompts: a compact multiline box with an "expand" button opening a large modal editor. Wired to `task_prompt` and `system_prompt`.

**Files:**
- Create: `web/src/components/LongTextField.tsx`
- Modify: `web/src/schema/widgets.tsx`, `web/src/schema/registry.ts`, `web/src/schema/uiSchema.ts:50`

- [ ] **Step 1: Create the component**

Create `web/src/components/LongTextField.tsx`:

```tsx
import { useState } from "react";
import {
  TextField, IconButton, InputAdornment, Dialog, DialogTitle,
  DialogContent, DialogActions, Button, Tooltip,
} from "@mui/material";
import OpenInFullIcon from "@mui/icons-material/OpenInFull";

interface Props {
  value: string;
  onChange: (next: string) => void;
  label?: string;
  helperText?: string;
  rows?: number;
}

export default function LongTextField({
  value, onChange, label = "Text", helperText, rows = 6,
}: Props) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <TextField
        label={label}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        helperText={helperText}
        multiline
        minRows={rows}
        maxRows={rows}
        fullWidth
        InputProps={{
          endAdornment: (
            <InputAdornment position="end" sx={{ alignSelf: "flex-start", mt: 1 }}>
              <Tooltip title="Expand">
                <IconButton size="small" onClick={() => setOpen(true)}>
                  <OpenInFullIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </InputAdornment>
          ),
        }}
      />
      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="md">
        <DialogTitle>{label}</DialogTitle>
        <DialogContent>
          <TextField
            value={value ?? ""}
            onChange={(e) => onChange(e.target.value)}
            multiline
            minRows={20}
            fullWidth
            autoFocus
            sx={{ mt: 1 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>Done</Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
```

- [ ] **Step 2: Add the rjsf widget wrapper**

Append to `web/src/schema/widgets.tsx`:

```tsx
import LongTextField from "../components/LongTextField";

export function LongTextWidget(props: WidgetProps) {
  return (
    <LongTextField
      value={(props.value as string) ?? ""}
      onChange={props.onChange}
      label={props.label}
      helperText={props.schema.description as string | undefined}
    />
  );
}
```

- [ ] **Step 3: Register it**

In `web/src/schema/registry.ts`, import `LongTextWidget` from `./widgets` and add it to `customWidgets`:

```typescript
import {
  ModelValidationWidget, TargetMethodsWidget, AugmentationWidget, LongTextWidget,
} from "./widgets";

export const customWidgets = {
  ModelValidationWidget, TargetMethodsWidget, AugmentationWidget, LongTextWidget,
};
```

- [ ] **Step 4: Bind it in uiSchema**

In `web/src/schema/uiSchema.ts`, replace the `system_prompt` line (line 50) and add `task_prompt`:

```typescript
  task_prompt:   { "ui:widget": "LongTextWidget" },
  system_prompt: { "ui:widget": "LongTextWidget" },
```

- [ ] **Step 5: Typecheck + build**

Run: `cd web && npm run build`
Expected: build succeeds.

- [ ] **Step 6: Manual smoke**

Run the dev server (`cd web && npm run dev`), open an experiment, confirm Task prompt + System prompt show a compact box with an expand icon that opens a large editor, and edits persist on Save.

- [ ] **Step 7: Commit**

```bash
git add web/src/components/LongTextField.tsx web/src/schema/widgets.tsx web/src/schema/registry.ts web/src/schema/uiSchema.ts
git commit -m "feat(web): expandable long-text widget for task/system prompts"
```

---

## Task 8: Frontend — ContextWindowField (autoload)

`model_context_window` autoloads from the endpoint using the model + its provider's base_url (read from `formContext.formData`), stays editable as a manual override.

**Files:**
- Create: `web/src/components/ContextWindowField.tsx`
- Modify: `web/src/schema/widgets.tsx`, `web/src/schema/registry.ts`, `web/src/schema/uiSchema.ts`, `web/src/pages/ExperimentEdit.tsx:167`

- [ ] **Step 1: Create the component**

Create `web/src/components/ContextWindowField.tsx`:

```tsx
import { useEffect, useState } from "react";
import { TextField, InputAdornment, CircularProgress, Typography } from "@mui/material";
import { fetchModelContext } from "../api/queries";

interface ProviderLike { id?: string; base_url?: string; api_key_env?: string | null }
interface Props {
  value: number | null;
  onChange: (next: number | null) => void;
  label?: string;
  model?: string;
  providers?: ProviderLike[];
}

export default function ContextWindowField({
  value, onChange, label = "Model context window", model, providers = [],
}: Props) {
  const [auto, setAuto] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);

  const prefix = model?.includes("/") ? model.split("/")[0] : undefined;
  const provider = providers.find((p) => p.id === prefix);
  const baseUrl = provider?.base_url ?? "";

  useEffect(() => {
    let cancelled = false;
    if (!model || !baseUrl) { setAuto(null); return; }
    setLoading(true);
    fetchModelContext(model, baseUrl, provider?.api_key_env ?? null)
      .then((r) => { if (!cancelled) setAuto(r.context_window); })
      .catch(() => { if (!cancelled) setAuto(null); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [model, baseUrl, provider?.api_key_env]);

  // Prefill the field once when empty and a window was detected.
  useEffect(() => {
    if ((value === null || value === undefined) && auto != null) onChange(auto);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auto]);

  const helper = loading
    ? "Detecting from endpoint…"
    : auto != null
      ? `Auto-detected: ${auto.toLocaleString()} tokens (editable override)`
      : "Set manually, or configure the model's provider to auto-detect.";

  return (
    <TextField
      label={label}
      type="number"
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
      helperText={helper}
      fullWidth
      InputProps={{
        endAdornment: loading ? (
          <InputAdornment position="end"><CircularProgress size={16} /></InputAdornment>
        ) : auto != null ? (
          <InputAdornment position="end">
            <Typography variant="caption" color="text.secondary">auto {auto.toLocaleString()}</Typography>
          </InputAdornment>
        ) : undefined,
      }}
    />
  );
}
```

- [ ] **Step 2: Add the rjsf widget wrapper (reads formContext)**

Append to `web/src/schema/widgets.tsx`:

```tsx
import ContextWindowField from "../components/ContextWindowField";

export function ContextWindowWidget(props: WidgetProps) {
  const fc = (props.formContext ?? {}) as {
    formData?: { model?: string; opencode?: { providers?: unknown[] } };
  };
  return (
    <ContextWindowField
      value={(props.value as number | null) ?? null}
      onChange={(v) => props.onChange(v)}
      label={props.label}
      model={fc.formData?.model}
      providers={(fc.formData?.opencode?.providers as never[]) ?? []}
    />
  );
}
```

- [ ] **Step 3: Register + bind**

In `web/src/schema/registry.ts`, add `ContextWindowWidget` to the `./widgets` import and to `customWidgets`.

In `web/src/schema/uiSchema.ts`, add:

```typescript
  model_context_window: { "ui:widget": "ContextWindowWidget" },
```

- [ ] **Step 4: Pass formData through formContext**

In `web/src/pages/ExperimentEdit.tsx:167`, extend the `formContext`:

```typescript
            formContext={{ detectedVerify: detected.data, onAddCustomEndpoint: handleAddEndpoint, formData }}
```

- [ ] **Step 5: Typecheck + build**

Run: `cd web && npm run build`
Expected: build succeeds.

- [ ] **Step 6: Manual smoke**

With a vLLM provider configured (base_url set) and a matching `model`, open the experiment: the context-window field shows "Detecting…" then prefills the detected value; editing it overrides.

- [ ] **Step 7: Commit**

```bash
git add web/src/components/ContextWindowField.tsx web/src/schema/widgets.tsx web/src/schema/registry.ts web/src/schema/uiSchema.ts web/src/pages/ExperimentEdit.tsx
git commit -m "feat(web): autoload model context window from the endpoint"
```

---

## Task 9: Frontend — AugmentationField (inline | file + verify)

Rewrite `AugmentationField` into a controlled component owning both the value AND its kind, with a segmented toggle, an inline textarea (reusing LongTextField), and a file path input with a live found/size/preview indicator.

**Files:**
- Modify: `web/src/components/AugmentationField.tsx`

- [ ] **Step 1: Rewrite the component**

Replace the entire contents of `web/src/components/AugmentationField.tsx`:

```tsx
import { useEffect, useState } from "react";
import {
  Stack, ToggleButton, ToggleButtonGroup, TextField, Typography, Chip,
} from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import ErrorIcon from "@mui/icons-material/Error";
import LongTextField from "./LongTextField";
import { verifyAugmentation } from "../api/queries";
import type { VerifyAugmentationResp } from "../api/types";

type Kind = "text" | "file";

interface Props {
  value: string;
  kind: Kind;
  onChange: (value: string, kind: Kind) => void;
  experimentName?: string;
  label?: string;
}

export default function AugmentationField({
  value, kind, onChange, experimentName, label = "Augmentation",
}: Props) {
  const [verify, setVerify] = useState<VerifyAugmentationResp | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (kind !== "file" || !value) { setVerify(null); return; }
    verifyAugmentation(value, experimentName)
      .then((r) => { if (!cancelled) setVerify(r); })
      .catch(() => { if (!cancelled) setVerify(null); });
    return () => { cancelled = true; };
  }, [kind, value, experimentName]);

  return (
    <Stack spacing={1}>
      <Stack direction="row" alignItems="center" spacing={1}>
        <Typography variant="subtitle2">{label}</Typography>
        <ToggleButtonGroup
          size="small"
          exclusive
          value={kind}
          onChange={(_e, k: Kind | null) => k && onChange(value, k)}
        >
          <ToggleButton value="text">Inline</ToggleButton>
          <ToggleButton value="file">File</ToggleButton>
        </ToggleButtonGroup>
      </Stack>

      {kind === "text" ? (
        <LongTextField
          label="Inline markdown"
          value={value}
          onChange={(v) => onChange(v, "text")}
          helperText="Stored as slices/<condition>.md on Save."
          rows={6}
        />
      ) : (
        <Stack spacing={0.5}>
          <TextField
            label="File path"
            value={value}
            onChange={(e) => onChange(e.target.value, "file")}
            placeholder="./slices/graph.md or /abs/path.md"
            fullWidth
            size="small"
          />
          {value && verify && (
            verify.found ? (
              <Chip
                icon={<CheckCircleIcon />}
                color="success"
                variant="outlined"
                size="small"
                label={`found · ${verify.size} B · ${verify.preview.split("\n")[0].slice(0, 60)}`}
              />
            ) : (
              <Chip icon={<ErrorIcon />} color="error" variant="outlined" size="small" label="not found" />
            )
          )}
        </Stack>
      )}
    </Stack>
  );
}
```

- [ ] **Step 2: Update the existing rjsf widget wrapper to the new signature**

The legacy `AugmentationWidget` in `web/src/schema/widgets.tsx` passed only `value`. Since augmentation is now edited inside the conditions modal (Task 10/11), update the wrapper so it still typechecks but defaults `kind` to `"text"` and ignores sibling writes (it will be superseded by the modal):

```tsx
export function AugmentationWidget(props: WidgetProps) {
  return (
    <AugmentationField
      value={(props.value as string) ?? ""}
      kind="text"
      onChange={(v) => props.onChange(v)}
      label={props.label}
    />
  );
}
```

- [ ] **Step 3: Typecheck + build**

Run: `cd web && npm run build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/AugmentationField.tsx web/src/schema/widgets.tsx
git commit -m "feat(web): augmentation inline|file toggle with file verification"
```

---

## Task 10: Frontend — condition sub-controls (tools, orchestration, engine)

Three small controlled MUI components used by the conditions modal.

**Files:**
- Create: `web/src/components/ToolsSelect.tsx`, `web/src/components/OrchestrationSelect.tsx`, `web/src/components/EngineSelect.tsx`

- [ ] **Step 1: ToolsSelect (multiselect + freeSolo)**

Create `web/src/components/ToolsSelect.tsx`:

```tsx
import { Autocomplete, TextField, Chip } from "@mui/material";

// Curated list: opencode built-ins worth gating + the gateable library tools.
// freeSolo lets an unknown tool still be typed.
const KNOWN_TOOLS = ["impact", "read", "grep", "glob", "list", "edit", "write", "bash"];

interface Props {
  value: string[];
  onChange: (next: string[]) => void;
  label?: string;
}

export default function ToolsSelect({ value, onChange, label = "Enabled tools" }: Props) {
  return (
    <Autocomplete
      multiple
      freeSolo
      size="small"
      options={KNOWN_TOOLS}
      value={value}
      onChange={(_e, v) => onChange(v as string[])}
      renderTags={(vals, getTagProps) =>
        vals.map((opt, i) => <Chip size="small" label={opt} {...getTagProps({ index: i })} key={opt} />)
      }
      renderInput={(params) => (
        <TextField
          {...params}
          label={label}
          helperText="A tool from opencode.tools_lib NOT listed here is disabled for this condition (preserves the A/B contrast)."
        />
      )}
    />
  );
}
```

- [ ] **Step 2: OrchestrationSelect (enum incl. autonomous/None)**

Create `web/src/components/OrchestrationSelect.tsx`:

```tsx
import { TextField, MenuItem } from "@mui/material";

type Mode = "phased" | "phased_plan" | "phased_graph" | "phased_runtime" | null;

const OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Autonomous (none)" },
  { value: "phased", label: "Phased" },
  { value: "phased_plan", label: "Phased + plan" },
  { value: "phased_graph", label: "Phased + graph focus" },
  { value: "phased_runtime", label: "Phased + runtime evidence" },
];

interface Props {
  value: Mode;
  onChange: (next: Mode) => void;
  label?: string;
}

export default function OrchestrationSelect({ value, onChange, label = "Orchestration" }: Props) {
  return (
    <TextField
      select
      size="small"
      fullWidth
      label={label}
      value={value ?? ""}
      onChange={(e) => onChange((e.target.value || null) as Mode)}
      helperText="None = autonomous opencode loop. Phased modes need the experiment-level orchestration block."
    >
      {OPTIONS.map((o) => <MenuItem key={o.value} value={o.value}>{o.label}</MenuItem>)}
    </TextField>
  );
}
```

- [ ] **Step 3: EngineSelect**

Create `web/src/components/EngineSelect.tsx`:

```tsx
import { TextField, MenuItem } from "@mui/material";

type Engine = "python" | "langgraph";

interface Props {
  value: Engine;
  onChange: (next: Engine) => void;
  disabled?: boolean;
  label?: string;
}

export default function EngineSelect({ value, onChange, disabled, label = "Engine" }: Props) {
  return (
    <TextField
      select
      size="small"
      fullWidth
      label={label}
      value={value ?? "python"}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value as Engine)}
      helperText={disabled ? "Applies only to phased modes." : "Phased controller implementation."}
    >
      <MenuItem value="python">Python</MenuItem>
      <MenuItem value="langgraph">LangGraph</MenuItem>
    </TextField>
  );
}
```

- [ ] **Step 4: Typecheck + build**

Run: `cd web && npm run build`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/ToolsSelect.tsx web/src/components/OrchestrationSelect.tsx web/src/components/EngineSelect.tsx
git commit -m "feat(web): condition sub-controls (tools, orchestration, engine)"
```

---

## Task 11: Frontend — ConditionsField (rows) + ConditionModal (editor)

Replace the default array rendering of `conditions` with compact rows + a focused modal that assembles all condition controls (name, augmentation+kind, tools, orchestration+engine, system-prompt override).

**Files:**
- Create: `web/src/components/ConditionModal.tsx`, `web/src/components/ConditionsField.tsx`
- Modify: `web/src/schema/registry.ts`, `web/src/schema/uiSchema.ts:21-30`

- [ ] **Step 1: Define the shared Condition type + the modal**

Create `web/src/components/ConditionModal.tsx`:

```tsx
import { useState } from "react";
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button, Stack, TextField,
} from "@mui/material";
import AugmentationField from "./AugmentationField";
import ToolsSelect from "./ToolsSelect";
import OrchestrationSelect from "./OrchestrationSelect";
import EngineSelect from "./EngineSelect";
import LongTextField from "./LongTextField";

export interface ConditionData {
  name: string;
  augmentation: string | null;
  augmentation_kind: "text" | "file";
  overlay: string | null;
  tools: string[];
  orchestration: "phased" | "phased_plan" | "phased_graph" | "phased_runtime" | null;
  engine: "python" | "langgraph";
  system_prompt: string | null;
}

export function emptyCondition(name = "baseline"): ConditionData {
  return {
    name, augmentation: null, augmentation_kind: "text", overlay: null,
    tools: [], orchestration: null, engine: "python", system_prompt: null,
  };
}

interface Props {
  open: boolean;
  initial: ConditionData;
  experimentName?: string;
  onClose: () => void;
  onSave: (c: ConditionData) => void;
}

export default function ConditionModal({ open, initial, experimentName, onClose, onSave }: Props) {
  const [c, setC] = useState<ConditionData>(initial);
  const set = <K extends keyof ConditionData>(k: K, v: ConditionData[K]) =>
    setC((prev) => ({ ...prev, [k]: v }));

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="md">
      <DialogTitle>Condition: {c.name || "(unnamed)"}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField
            label="Name"
            size="small"
            value={c.name}
            onChange={(e) => set("name", e.target.value)}
            helperText="e.g. baseline, augmented"
          />
          <AugmentationField
            value={c.augmentation ?? ""}
            kind={c.augmentation_kind}
            experimentName={experimentName}
            onChange={(v, kind) => setC((p) => ({ ...p, augmentation: v || null, augmentation_kind: kind }))}
          />
          <ToolsSelect value={c.tools} onChange={(v) => set("tools", v)} />
          <Stack direction="row" spacing={2}>
            <OrchestrationSelect value={c.orchestration} onChange={(v) => set("orchestration", v)} />
            <EngineSelect
              value={c.engine}
              disabled={c.orchestration === null}
              onChange={(v) => set("engine", v)}
            />
          </Stack>
          <TextField
            label="Overlay directory (optional)"
            size="small"
            value={c.overlay ?? ""}
            onChange={(e) => set("overlay", e.target.value || null)}
            helperText="Per-session tool files copied into the workdir; blank = none."
          />
          <LongTextField
            label="System prompt override (optional)"
            value={c.system_prompt ?? ""}
            onChange={(v) => set("system_prompt", v || null)}
            helperText="Blank = use the experiment-level system prompt."
            rows={4}
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={!c.name.trim()} onClick={() => onSave(c)}>Save condition</Button>
      </DialogActions>
    </Dialog>
  );
}
```

- [ ] **Step 2: Create the ConditionsField (rjsf field replacement)**

Create `web/src/components/ConditionsField.tsx`:

```tsx
import { useState } from "react";
import type { FieldProps } from "@rjsf/utils";
import {
  Stack, Typography, Button, Paper, IconButton, Chip, Box, Tooltip,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import EditIcon from "@mui/icons-material/Edit";
import DeleteIcon from "@mui/icons-material/Delete";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import ConditionModal, { type ConditionData, emptyCondition } from "./ConditionModal";

const ORCH_LABEL: Record<string, string> = {
  phased: "phased", phased_plan: "phased+plan",
  phased_graph: "phased+graph", phased_runtime: "phased+runtime",
};

function augChip(c: ConditionData): string {
  if (!c.augmentation) return "baseline";
  return c.augmentation_kind === "file" ? "file" : "inline";
}

export default function ConditionsField(props: FieldProps) {
  const value = (Array.isArray(props.formData) ? props.formData : []) as ConditionData[];
  const experimentName = (props.formContext as { formData?: { name?: string } })?.formData?.name;
  const [editing, setEditing] = useState<number | null>(null);

  const commit = (next: ConditionData[]) => props.onChange(next);
  const upsert = (c: ConditionData) => {
    const next = [...value];
    if (editing != null && editing < value.length) next[editing] = c;
    else next.push(c);
    commit(next);
    setEditing(null);
  };

  return (
    <Box>
      <Stack direction="row" alignItems="center" sx={{ mb: 1 }}>
        <Typography variant="subtitle1" sx={{ flexGrow: 1 }}>Conditions</Typography>
        <Button startIcon={<AddIcon />} size="small"
          onClick={() => setEditing(value.length)}>Add condition</Button>
      </Stack>
      <Stack spacing={1}>
        {value.map((c, i) => (
          <Paper key={i} variant="outlined" sx={{ p: 1, display: "flex", alignItems: "center", gap: 1 }}>
            <Typography sx={{ fontWeight: 600, minWidth: 120 }}>{c.name || `#${i + 1}`}</Typography>
            <Chip size="small" label={augChip(c)} />
            <Chip size="small" variant="outlined"
              label={c.tools.length ? `+${c.tools.join(",")}` : "no tools"} />
            <Chip size="small" variant="outlined"
              label={c.orchestration ? ORCH_LABEL[c.orchestration] : "autonomous"} />
            {c.orchestration && <Chip size="small" variant="outlined" label={c.engine} />}
            {c.system_prompt && <Chip size="small" color="info" variant="outlined" label="sys override" />}
            <Box sx={{ flexGrow: 1 }} />
            <Tooltip title="Edit"><IconButton size="small" onClick={() => setEditing(i)}><EditIcon fontSize="small" /></IconButton></Tooltip>
            <Tooltip title="Duplicate"><IconButton size="small" onClick={() => {
              const copy = { ...c, name: `${c.name}-copy` };
              commit([...value.slice(0, i + 1), copy, ...value.slice(i + 1)]);
            }}><ContentCopyIcon fontSize="small" /></IconButton></Tooltip>
            <Tooltip title="Remove"><IconButton size="small" onClick={() => commit(value.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton></Tooltip>
          </Paper>
        ))}
        {value.length === 0 && (
          <Typography variant="body2" color="text.secondary">No conditions yet — add at least one (e.g. baseline).</Typography>
        )}
      </Stack>
      {editing != null && (
        <ConditionModal
          open
          key={editing}
          initial={value[editing] ?? emptyCondition(value.length === 0 ? "baseline" : "augmented")}
          experimentName={experimentName}
          onClose={() => setEditing(null)}
          onSave={upsert}
        />
      )}
    </Box>
  );
}
```

- [ ] **Step 3: Register the field + bind it in uiSchema**

In `web/src/schema/registry.ts`, import and register:

```typescript
import ConditionsField from "../components/ConditionsField";
// ...
export const customFields = { VerifyField, ConditionsField };
```

In `web/src/schema/uiSchema.ts`, replace the `conditions` block (lines 21-30) with:

```typescript
  conditions: { "ui:field": "ConditionsField" },
```

Remove the now-unused `import ConditionItemTemplate from "./ConditionItemTemplate";` line at the top of `uiSchema.ts` (the field replacement supersedes the per-item template).

- [ ] **Step 4: Typecheck + build**

Run: `cd web && npm run build`
Expected: build succeeds.

- [ ] **Step 5: Manual smoke**

Open an experiment: conditions render as rows with name + chips; "Add condition" and the row Edit pencil open the modal; saving the modal updates the row; the augmentation File mode shows the found/size indicator; Save → reload shows the same conditions (round-trip).

- [ ] **Step 6: Commit**

```bash
git add web/src/components/ConditionModal.tsx web/src/components/ConditionsField.tsx web/src/schema/registry.ts web/src/schema/uiSchema.ts
git commit -m "feat(web): conditions as rows + focused modal editor"
```

---

## Task 12: Frontend — information architecture (groups) + help

Group the primary fields under Basics / Task / Conditions / Run headers above the Advanced accordion, and route the new set-once/power-user fields into Advanced.

**Files:**
- Modify: `web/src/schema/RootObjectFieldTemplate.tsx`, `web/src/schema/uiSchema.ts:9-13`

- [ ] **Step 1: Add named groups to the root template**

Replace `web/src/schema/RootObjectFieldTemplate.tsx`'s `ADVANCED` set + the root branch. First, replace the `ADVANCED` set (lines 10-18) with a group map + advanced set:

```typescript
// Primary fields grouped under light headers; everything else falls to Advanced.
const GROUPS: { title: string; fields: string[] }[] = [
  { title: "Basics", fields: ["name", "model", "model_context_window"] },
  { title: "Task", fields: ["task_prompt", "system_prompt", "target_file", "target_methods", "fixture_path", "reference_path"] },
  { title: "Conditions", fields: ["conditions"] },
  { title: "Run", fields: ["repetitions", "verify"] },
];
const PRIMARY = new Set<string>(GROUPS.flatMap((g) => g.fields));
```

Then replace the root return branch (lines 60-79) with grouped rendering:

```typescript
  const grouped: Record<string, ObjectFieldTemplatePropertyType[]> = {};
  const advanced: ObjectFieldTemplatePropertyType[] = [];
  const byName = new Map(props.properties.map((p) => [p.name, p]));
  for (const p of props.properties) {
    if (!PRIMARY.has(p.name)) advanced.push(p);
  }

  return (
    <Box>
      {header}
      {GROUPS.map((g) => {
        const items = g.fields.map((f) => byName.get(f)).filter(Boolean) as ObjectFieldTemplatePropertyType[];
        if (items.length === 0) return null;
        return (
          <Box key={g.title} sx={{ mb: 2 }}>
            <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 0.5 }}>{g.title}</Typography>
            {renderProps(items)}
          </Box>
        );
      })}
      {advanced.length > 0 && (
        <Accordion defaultExpanded={false} sx={{ mt: 1 }}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography>Advanced (output, timeouts, isolation, metrics, opencode, orchestration)</Typography>
          </AccordionSummary>
          <AccordionDetails>{renderProps(advanced)}</AccordionDetails>
        </Accordion>
      )}
    </Box>
  );
```

(The non-root branch at lines 56-58 stays unchanged.)

- [ ] **Step 2: Simplify ui:order to the group flow**

In `web/src/schema/uiSchema.ts`, replace the `ui:order` (lines 9-13):

```typescript
  "ui:order": [
    "name", "model", "model_context_window",
    "task_prompt", "system_prompt", "target_file", "target_methods",
    "fixture_path", "reference_path",
    "conditions", "repetitions", "verify", "*",
  ],
```

- [ ] **Step 3: Typecheck + build**

Run: `cd web && npm run build`
Expected: build succeeds.

- [ ] **Step 4: Manual smoke**

Open an experiment: fields appear under Basics / Task / Conditions / Run headers; `output_dir`, `timeout_s`, rate-limit, `isolation`, `metrics`, `opencode`, and the `orchestration` block sit inside a collapsed Advanced accordion; no validation error is hidden (required identity fields are all primary).

- [ ] **Step 5: Commit**

```bash
git add web/src/schema/RootObjectFieldTemplate.tsx web/src/schema/uiSchema.ts
git commit -m "feat(web): Basics/Task/Conditions/Run groups + Advanced accordion"
```

---

## Task 13: Full verification sweep

- [ ] **Step 1: Backend test suite**

Run: `python3 -m pytest -q`
Expected: PASS (parity tests skip if `langgraph` is absent).

- [ ] **Step 2: Frontend build**

Run: `cd web && npm run build`
Expected: succeeds with no TS errors.

- [ ] **Step 3: End-to-end smoke (manual)**

Start the UI, create a new experiment, add a baseline + an augmented condition (one inline, one file with a valid path showing ✓), set `phased_runtime` + `langgraph` on one condition, autoload a context window, Save, reload — confirm everything round-trips — then start a short run to confirm the runner accepts the new fields (system-prompt override applied, engine respected).

- [ ] **Step 4: Final commit (if any residual changes)**

```bash
git add -A
git commit -m "chore: experiment-form redesign — verification sweep"
```

---

## Self-review notes (resolved during planning)

- **`compose` is intentionally unchanged** — augmentation reaches the runner already resolved to text; file-vs-text is handled at the storage/round-trip layer (Task 4), not the prompt layer.
- **Env-as-override for engine** — `ABENCH_ORCHESTRATOR` keeps its current global-force semantics; per-condition `engine` is the default when the env var is unset (Task 3). This deviates from the spec's "env fallback" wording in favor of back-compat; called out in the test `test_env_overrides_condition_engine`.
- **Conditions use a bespoke modal**, not the rjsf object field — the inline/file augmentation toggle must write two sibling props (`augmentation` + `augmentation_kind`), which an rjsf widget cannot do. The modal owns the whole condition object (Tasks 10–11).
- **Enum labels** for orchestration/engine come from the bespoke selects (Task 10), sidestepping rjsf `enumNames` uncertainty and giving the `None`→"Autonomous" option a clean label.
- **No frontend test harness** exists; frontend tasks gate on `npm run build` (tsc) + a stated manual smoke. If a vitest harness is added later, the new components are pure/controlled and unit-testable.
