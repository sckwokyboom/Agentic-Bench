# Per-condition agent temperature — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-condition `temperature` knob that is applied to the opencode agent (autonomous + phased), persisted into the run record, and surfaced in the web UI.

**Architecture:** opencode's `AgentConfig` block accepts `temperature`; we already write that block in `build_opencode_config`. We add a `Condition.temperature` field, thread it to `run_task` (both the autonomous call and the phased `make_phase_runner`), record the applied value on the `Trace` (→ `trace.json`) and in `metrics.json`, then expose it through `abench_ui` / `safe_trace` to the React app. `null` = unset = provider default (no behaviour change).

**Tech Stack:** Python 3.14, pydantic v2, pytest; React + TypeScript + MUI (web).

**Spec:** `docs/superpowers/specs/2026-06-30-per-condition-temperature-design.md`

---

### Task 1: `Condition.temperature` config field

**Files:**
- Modify: `abench/config.py` (the `Condition` model, after `system_augmentation`, ends ~line 117)
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_condition_temperature_parses_and_defaults(tmp_path):
    from abench.config import Condition
    assert Condition(name="c").temperature is None
    assert Condition(name="c", temperature=0.7).temperature == 0.7


def test_condition_temperature_out_of_range_rejected():
    from abench.config import Condition
    with pytest.raises(Exception):
        Condition(name="c", temperature=2.5)
    with pytest.raises(Exception):
        Condition(name="c", temperature=-0.1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -k temperature -v`
Expected: FAIL — `temperature` not a field / no validation error raised.

- [ ] **Step 3: Add the field**

In `abench/config.py`, inside `class Condition(BaseModel)`, immediately after the `system_augmentation` field (the last field, ~line 117), add:

```python
    temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
        title="Temperature",
        description=(
            "Sampling temperature for THIS condition's agent (0–2; lower = more "
            "deterministic). Written into the run's opencode.json agent block and "
            "forwarded to the provider verbatim. Blank = leave the provider "
            "default (current behaviour). Useful as an A/B variable: e.g. a "
            "temp=0 arm vs a temp=0.7 arm of the same task."
        ),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -k temperature -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add abench/config.py tests/test_config.py
git commit -m "feat(ab): add per-condition temperature config field"
```

---

### Task 2: `Trace.temperature` provenance field

**Files:**
- Modify: `abench/trace_model.py` (the `Trace` dataclass, next to `model`, ~line 84)
- Test: `tests/test_trace_model.py` (create if absent)

`to_dict()` uses `asdict` and `trace_from_dict` uses `**remaining`, so a new field round-trips automatically — the test guards that contract.

- [ ] **Step 1: Write the failing test**

Create/append `tests/test_trace_model.py`:

```python
from abench.trace_model import Trace, trace_from_dict


def test_trace_temperature_roundtrips():
    t = Trace(temperature=0.7)
    d = t.to_dict()
    assert d["temperature"] == 0.7
    assert trace_from_dict(d).temperature == 0.7


def test_trace_temperature_defaults_none():
    assert Trace().temperature is None
    assert trace_from_dict(Trace().to_dict()).temperature is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_trace_model.py -k temperature -v`
Expected: FAIL — `Trace` has no `temperature` attribute.

- [ ] **Step 3: Add the field**

In `abench/trace_model.py`, inside `@dataclass class Trace`, directly after the `model: str | None = None` / `provider: str | None = None` lines (~line 84-85), add:

```python
    # Sampling temperature REQUESTED for this run (the value written into the
    # opencode.json agent block), or None when left at the provider default.
    # Recorded like `model`: provenance of what we asked for — a provider may
    # silently ignore it.
    temperature: float | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_trace_model.py -k temperature -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add abench/trace_model.py tests/test_trace_model.py
git commit -m "feat(ab): record requested temperature on Trace"
```

---

### Task 3: Apply temperature in `build_opencode_config` + `run_task`

**Files:**
- Modify: `abench/opencode_client.py` (`build_opencode_config` ~line 125; `OpenCodeClient` Protocol ~line 345; `RealOpenCodeClient.run_task` ~line 393 + the `config_data =` call ~line 429 + trace assembly ~line 652)
- Test: `tests/test_opencode_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_opencode_config.py`:

```python
def test_temperature_set_on_agent_block_when_provided():
    cfg = OpenCodeCfg()
    config = build_opencode_config(cfg, "openrouter/x", "sys", temperature=0.7)
    assert config["agent"][cfg.agent]["temperature"] == 0.7


def test_temperature_omitted_when_none_keeps_output_unchanged():
    cfg = OpenCodeCfg()
    config = build_opencode_config(cfg, "openrouter/x", "sys", temperature=None)
    assert "temperature" not in config["agent"][cfg.agent]
    # byte-identical to the no-temperature call
    assert config == build_opencode_config(cfg, "openrouter/x", "sys")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_opencode_config.py -k temperature -v`
Expected: FAIL — `build_opencode_config` got an unexpected keyword `temperature`.

- [ ] **Step 3: Implement**

In `abench/opencode_client.py`:

(a) Update the signature and agent block of `build_opencode_config` (~line 125-149). Change the signature line and add the temperature key after the `agent_tools` handling:

```python
def build_opencode_config(
    cfg: OpenCodeCfg,
    model: str,
    system_prompt: str,
    agent_tools: dict[str, bool] | None = None,
    temperature: float | None = None,
) -> dict:
```

and right after the existing `if agent_tools:` block:

```python
    if agent_tools:
        agent_block["tools"] = agent_tools
    # opencode's AgentConfig accepts `temperature`; forward it verbatim. Omit the
    # key entirely when None so the provider default is used (output unchanged).
    if temperature is not None:
        agent_block["temperature"] = temperature
```

(b) Add `temperature` to the `OpenCodeClient` Protocol's `run_task` (~line 345-360), after `agent_tools`:

```python
        agent_tools: "dict[str, bool] | None" = None,
        temperature: "float | None" = None,
```

(c) Add the same parameter to `RealOpenCodeClient.run_task` (~line 393-405), after `agent_tools`:

```python
        agent_tools: "dict[str, bool] | None" = None,
        temperature: "float | None" = None,
```

(d) Pass it into the config build (~line 429):

```python
        config_data = build_opencode_config(
            self._cfg, model, system_prompt, agent_tools=agent_tools,
            temperature=temperature,
        )
```

(e) Record it on the trace, next to the `trace.model` fallback (~line 652, after `trace.model = model`):

```python
        if not trace.model:
            trace.model = model
        trace.temperature = temperature
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_opencode_config.py -v`
Expected: PASS (new + existing tests — the omit-when-None test guarantees no regression).

- [ ] **Step 5: Commit**

```bash
git add abench/opencode_client.py tests/test_opencode_config.py
git commit -m "feat(ab): thread temperature through build_opencode_config + run_task"
```

---

### Task 4: Forward temperature in `make_phase_runner` (phased)

**Files:**
- Modify: `abench/orchestration_adapters.py` (`make_phase_runner` ~line 161-181)
- Test: `tests/test_orchestration_adapters.py` (the existing `_FakeClient` in `test_make_phase_runner_scopes_tools_and_extracts_text`, ~line 77-104)

- [ ] **Step 1: Update the failing test**

In `tests/test_orchestration_adapters.py`, update the `_FakeClient.run_task` signature to accept `temperature`, capture it, and assert it is forwarded. Replace the `run_task` method (~line 85) with:

```python
        def run_task(self, *, workdir, system_prompt, model, user_message,
                     timeout_s, agent_tools, on_event, cancel_event=None,
                     temperature=None):
            calls.update(workdir=workdir, model=model, user_message=user_message,
                         agent_tools=agent_tools, cancel_event=cancel_event,
                         temperature=temperature)
            return _Res(Trace(steps=[Step(kind=StepKind.ASSISTANT_TEXT, ts=1.0,
                                          text="CONTRACT: ...")]))
```

and update the `make_phase_runner(...)` call (~line 93) to pass a temperature, then assert it:

```python
    runner = make_phase_runner(_FakeClient(), workdir="/wd", system_prompt="sys",
                               model="m", timeout_s=60, on_event=lambda e: None,
                               cancel_event=sentinel, temperature=0.3)
```

and add after the existing `cancel_event` assertion (~line 99):

```python
    assert calls["temperature"] == 0.3          # forwarded into the phase's run_task
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_orchestration_adapters.py -k make_phase_runner -v`
Expected: FAIL — `make_phase_runner` got an unexpected keyword `temperature`.

- [ ] **Step 3: Implement**

In `abench/orchestration_adapters.py`, update `make_phase_runner` (~line 161) signature and the inner `run_task` call (~line 176):

```python
def make_phase_runner(client, *, workdir, system_prompt, model, timeout_s, on_event,
                      cancel_event=None, temperature=None):
```

```python
    def runner(phase: str, prompt: str, allowed_tools: list[str]) -> PhaseOutcome:
        res = client.run_task(
            workdir=str(workdir), system_prompt=system_prompt, model=model,
            user_message=prompt, timeout_s=timeout_s,
            agent_tools={t: True for t in allowed_tools}, on_event=on_event,
            cancel_event=cancel_event, temperature=temperature,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_orchestration_adapters.py -k make_phase_runner -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add abench/orchestration_adapters.py tests/test_orchestration_adapters.py
git commit -m "feat(ab): forward temperature into phased run_task"
```

---

### Task 5: Wire `cond.temperature` in the runner

**Files:**
- Modify: `abench/runner.py` (the autonomous `client.run_task(...)` ~line 613-624; the `make_phase_runner(...)` call ~line 548-552)

No new unit test — `cond` is the in-scope `Condition`; this is the wiring covered end-to-end by the integration suite (`tests/test_run_*`). Run the suite to confirm no regression.

- [ ] **Step 1: Pass temperature in the autonomous call**

In `abench/runner.py`, in the `else:` branch (~line 613), add `temperature=cond.temperature` to the `client.run_task(...)` call:

```python
                    result = client.run_task(
                        workdir=str(workdir),
                        system_prompt=system_prompt_eff,
                        model=exp.model,
                        user_message=user_message,
                        timeout_s=exp.timeout_s,
                        agent_tools=agent_tools,
                        on_event=on_event,
                        log_sink=readable_sink,
                        debug_sink=debug_sink,
                        cancel_event=cancel_event,
                        temperature=cond.temperature,
                    )
```

- [ ] **Step 2: Pass temperature in the phased call**

In `abench/runner.py`, in the `make_phase_runner(...)` call (~line 548), add `temperature=cond.temperature`:

```python
                    phase_runner = make_phase_runner(
                        client, workdir=str(workdir),
                        system_prompt=system_prompt_eff, model=exp.model,
                        timeout_s=exp.timeout_s, on_event=on_event,
                        cancel_event=cancel_event, temperature=cond.temperature)
```

- [ ] **Step 3: Run the runner suite to verify no regression**

Run: `python -m pytest tests/test_run_e2e.py tests/test_runner_isolation.py -v`
Expected: PASS (no signature/contract break).

- [ ] **Step 4: Commit**

```bash
git add abench/runner.py
git commit -m "feat(ab): apply per-condition temperature in runner (autonomous + phased)"
```

---

### Task 6: Persist temperature into `metrics.json`

**Files:**
- Modify: `abench/metrics.py` (the `extract` return dict, after `"cost": trace.cost,` ~line 179)
- Test: `tests/test_metrics.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_metrics.py` (match the file's existing way of constructing a `Trace` + `MetricsConfig`; minimal trace is fine):

```python
def test_extract_carries_temperature():
    from abench.metrics import extract, MetricsConfig
    from abench.trace_model import Trace
    m = extract(Trace(temperature=0.7), "", MetricsConfig())
    assert m["temperature"] == 0.7
    m0 = extract(Trace(), "", MetricsConfig())
    assert m0["temperature"] is None
```

> If `MetricsConfig()` needs args, copy the construction from an existing test in `tests/test_metrics.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_metrics.py -k temperature -v`
Expected: FAIL — `KeyError: 'temperature'`.

- [ ] **Step 3: Implement**

In `abench/metrics.py`, in the `extract(...)` return dict, immediately after `"cost": trace.cost,` (~line 179), add:

```python
        "cost": trace.cost,
        "temperature": trace.temperature,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_metrics.py -k temperature -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add abench/metrics.py tests/test_metrics.py
git commit -m "feat(ab): record temperature in metrics.json"
```

---

### Task 7: Expose temperature in the safe trace

**Files:**
- Modify: `abench/safe_trace.py` (the `safe_trace(...)` return dict, after `"provider": ...` ~line 183)
- Test: `tests/test_safe_trace.py` (match its existing call signature for `safe_trace`)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_safe_trace.py` (reuse the helper/scrubber pattern already in that file; the key assertion):

```python
def test_safe_trace_exposes_temperature():
    from abench.safe_trace import safe_trace, Scrubber
    out = safe_trace({"temperature": 0.7}, {}, Scrubber(), include_outputs=False)
    assert out["temperature"] == 0.7
```

> If `safe_trace`'s required kwargs differ, copy them from an existing test in the file.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_safe_trace.py -k temperature -v`
Expected: FAIL — `KeyError: 'temperature'`.

- [ ] **Step 3: Implement**

In `abench/safe_trace.py`, in the `safe_trace(...)` return dict, after the `"provider": scr.text(trace.get("provider")),` line (~line 183), add:

```python
        "provider": scr.text(trace.get("provider")),
        "temperature": trace.get("temperature"),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_safe_trace.py -k temperature -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add abench/safe_trace.py tests/test_safe_trace.py
git commit -m "feat(ab): expose temperature in safe trace"
```

---

### Task 8: Surface temperature in the runs API

**Files:**
- Modify: `abench_ui/runs.py` (`list_runs` per-run dict, near `"cost": m.get("cost"),` ~line 68)
- Test: `tests/abench_ui/test_runs_api.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/abench_ui/test_runs_api.py` (reuse the file's existing fixture that writes a `metrics.json` into a `condition/rep_N` layout; the assertion):

```python
def test_list_runs_includes_temperature(tmp_path):
    from abench_ui.runs import list_runs
    rep = tmp_path / "baseline" / "rep_0"
    rep.mkdir(parents=True)
    (rep / "metrics.json").write_text(json.dumps({"temperature": 0.7}))
    rows = list_runs(tmp_path)
    assert rows and rows[0]["temperature"] == 0.7
```

> Match the import style (`import json`) and any existing helper in the file; if the test module already has a `_write_run` helper, use it instead of hand-writing the dir.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/abench_ui/test_runs_api.py -k temperature -v`
Expected: FAIL — `KeyError: 'temperature'`.

- [ ] **Step 3: Implement**

In `abench_ui/runs.py`, in the `list_runs` per-run dict, after `"cost": m.get("cost"),` (~line 68), add:

```python
                "cost": m.get("cost"),
                "temperature": m.get("temperature"),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/abench_ui/test_runs_api.py -k temperature -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add abench_ui/runs.py tests/abench_ui/test_runs_api.py
git commit -m "feat(ab): expose temperature in /api/runs"
```

---

### Task 9: Web — type + display

**Files:**
- Modify: `web/src/api/types.ts` (`RunSummary` ~line 47; `Trace` ~line 215-242)
- Modify: `web/src/pages/TraceView.tsx` (chip row near the orchestration chip ~line 132-138)

The chip mirrors the existing context/orchestration chips: shown only when a temperature was set (`!= null`).

- [ ] **Step 1: Add the types**

In `web/src/api/types.ts`, in `RunSummary` after `cost: number | null;` (~line 47):

```typescript
  cost: number | null;
  temperature?: number | null;   // sampling temperature requested for the run (null = provider default)
```

and in the `Trace` interface, after `model_context_window?: number | null;` (~line 230):

```typescript
  temperature?: number | null;   // requested sampling temperature (null = provider default)
```

- [ ] **Step 2: Display the chip in TraceView**

In `web/src/pages/TraceView.tsx`, add a chip after the orchestration chip block (after the closing of the `{trace.data.orchestration_outcome && ( … )}` block, ~line 145), reusing the already-imported `Chip`:

```tsx
        {trace.data.temperature != null && (
          <Chip size="small" variant="outlined"
            label={`temperature: ${trace.data.temperature}`} sx={{ width: "fit-content" }} />
        )}
```

- [ ] **Step 3: Verify the web build typechecks**

Run: `cd web && npm run build` (or `npx tsc --noEmit`)
Expected: no TypeScript errors.

- [ ] **Step 4: Commit**

```bash
git add web/src/api/types.ts web/src/pages/TraceView.tsx
git commit -m "feat(ab): show requested temperature in the trace view"
```

---

### Task 10: Full-suite regression + example config

**Files:**
- Modify: `experiments/picocli-putValue/experiment.yaml` (document the knob — optional but recommended)

- [ ] **Step 1: Run the Python suite**

Run: `python -m pytest -q`
Expected: PASS (no regressions). Investigate any failure before proceeding.

- [ ] **Step 2: (Optional) Add a commented example to a tracked experiment**

In `experiments/picocli-putValue/experiment.yaml`, under the `conditions:` list, add a comment near the first condition documenting the new field, e.g.:

```yaml
conditions:
  # Optional per-condition `temperature: 0.0..2.0` (blank = provider default).
  # Vary it across conditions to A/B sampling temperature itself.
  - {name: baseline,  augmentation: null, tools: []}
```

- [ ] **Step 3: Commit**

```bash
git add experiments/picocli-putValue/experiment.yaml
git commit -m "docs(ab): document per-condition temperature in example experiment"
```

---

## Notes for the implementer

- **Pure-function first:** `build_opencode_config` is pure and unit-tested — get Task 3 green before the runner wiring; it's the load-bearing change.
- **No behaviour change when unset:** every `temperature` defaults to `None`, the agent-block key is omitted, and the omit-when-None test in Task 3 guards byte-identical output. Existing experiments and run records are unaffected.
- **Provenance vs metric:** temperature is provenance (like `model`), NOT a metric to average — do not add it to `report.py`'s `NUMERIC` aggregation list.
- **`report.py` needs no code change** (deliberate refinement of spec component #7): its source is `metrics.json`, which now carries `temperature` (Task 6), and `summary_json` only aggregates `NUMERIC` columns — temperature is provenance, not an aggregate. The per-run provenance therefore already lands in `metrics.json` + `trace.json`; the web reads it via `abench_ui/runs.py` (Task 8) and `safe_trace` (Task 7).
- **Test-file conventions:** where a test step says "match the file's existing pattern", read 10–15 lines of that test module first and mirror its fixtures/imports rather than inventing new ones.
