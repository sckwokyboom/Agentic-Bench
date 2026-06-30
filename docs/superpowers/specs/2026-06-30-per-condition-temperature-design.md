# Per-condition agent temperature — design

**Date:** 2026-06-30
**Status:** Approved (pending spec review)

## Problem

A run currently has no way to set the agent's sampling **temperature**. The
operator wants to control it per run, and — because temperature is itself an
interesting A/B variable — to vary it **per condition** (e.g. `temp=0` vs
`temp=0.7` as two arms of the same experiment). Today opencode falls back to the
provider default, which is undocumented and unreported, so runs aren't fully
reproducible. The existing specs already call for a *reported* temperature
(`2026-05-27-agentic-bench-design.md`, `2026-06-23-phased-orchestration-design.md`).

## Decisions (locked)

- **Scope:** per-condition only. No experiment-level global default — YAGNI; each
  condition carries its own. `null` = don't set → provider default (unchanged
  behaviour).
- **Coverage:** both the autonomous opencode loop **and** phased orchestration
  conditions honour it (no silent ignore for phased arms).
- **Provenance:** the temperature actually applied is **persisted** into the
  run's `trace.json` and **surfaced** in the web UI / report.
- **Out of scope:** `small_model` (the titles/summaries helper) is left at
  provider default — it is not part of what the experiment measures.

## Architecture

opencode's config schema exposes `temperature` on the **AgentConfig** block
(verified against `https://opencode.ai/config.json`, opencode 1.15.11). We
already write exactly that block in `build_opencode_config`
(`agent.<name> = {prompt, model, …}`), so applying temperature is a one-key
addition there. Everything else is threading the value to that point and
recording what was applied.

### Data flow

```
Condition.temperature (YAML / Run dialog)
  └─ runner.py:613  (autonomous)  ──┐
  └─ make_phase_runner (phased)   ──┤→ run_task(..., temperature=cond.temperature)
                                     └→ build_opencode_config(..., temperature)
                                          └→ agent_block["temperature"] = temperature   # only if not None
        run_task also sets trace.temperature = temperature   # ground-truth provenance, like trace.model
                                          └→ trace.json  ──→ safe_trace ──→ web RunSummary ──→ UI
                                                          └─ report.py summary columns / CSV
```

## Components & changes

1. **`abench/config.py` — `Condition.temperature`**
   - `temperature: float | None = Field(default=None, ge=0, le=2, title="Temperature", description=…)`.
   - `null` = provider default. Bounds 0–2 (the broadest provider range; opencode
     forwards verbatim). Field metadata makes it appear automatically in the web
     Run-dialog form (same mechanism as the other `Condition` fields).

2. **`abench/opencode_client.py`**
   - `build_opencode_config(cfg, model, system_prompt, agent_tools=None, temperature=None)`:
     `if temperature is not None: agent_block["temperature"] = temperature`.
     (Pure; unit-testable. Omitting the key when `None` keeps baseline output
     byte-identical to today.)
   - `run_task(..., temperature: float | None = None)`: forwards to
     `build_opencode_config` and sets `trace.temperature = temperature` after the
     trace is built (records *what we requested* — same caveat as `trace.model`:
     a provider may ignore it).
   - `OpenCodeClient` Protocol signature updated to match.

3. **`abench/trace_model.py` — `Trace.temperature: float | None = None`**
   - Added next to `model` (provenance group); included in `to_dict()`.

4. **`abench/runner.py`** (line ~613, autonomous path)
   - `client.run_task(..., temperature=cond.temperature)`.
   - The phased path builds its runner via `make_phase_runner(...)` — pass
     `temperature=cond.temperature` there too.

5. **`abench/orchestration_adapters.py` — `make_phase_runner(..., temperature=None)`**
   - Forward `temperature` into each phase's `client.run_task(...)`.

6. **`abench/safe_trace.py`**
   - Add `"temperature": trace.get("temperature")` to the allowlisted safe trace
     (a plain number — no scrubbing needed).

7. **`abench/report.py`**
   - Include `temperature` in the per-run summary so it lands in the report/CSV
     provenance alongside `model`.

8. **Web**
   - `web/src/api/types.ts`: `temperature?: number | null` on `RunSummary`.
   - Display: show the per-run temperature in the run/trace detail provenance
     (where `model` is shown). Not a new Runs-table column — it's provenance, not
     a comparison metric; keep the table comparison-focused (consistent with the
     just-merged tokens/cost-footer change).

## Error handling

- Invalid temperature (e.g. `> 2`, negative) is rejected at config-load time by
  the pydantic bounds → clear `ValidationError`, never reaches opencode.
- `null` / unset → key omitted → provider default → no behaviour change. This is
  the migration path: every existing experiment.yaml keeps working untouched.
- A provider that silently ignores temperature is the same situation as model
  attribution today; we record the *requested* value and document the caveat
  (already noted in `2026-05-27-agentic-bench-design.md`).

## Testing

- **config:** a condition with `temperature: 0.7` parses; out-of-range raises;
  omitted → `None`.
- **build_opencode_config:** `temperature=0.7` → `agent.<name>.temperature == 0.7`;
  `temperature=None` → key absent (byte-identical to current output).
- **run_task:** threads temperature into the written `opencode.json` and sets
  `trace.temperature` (assert via the fake/real client used in existing
  `test_run_*`).
- **phased:** `make_phase_runner` forwards temperature into `run_task`.
- **safe_trace/report:** `temperature` round-trips into the safe trace and
  summary.

## Migration / compatibility

No data migration. Existing experiments and runs (no `temperature` key) load as
`None` everywhere and behave exactly as before. The web `RunSummary` field is
optional, so older run records without it render fine.
