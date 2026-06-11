# Graph-Tipper as an installable OpenCode tool (bench-first) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the `GRAPH_TIPPER_HOME` env var and the per-experiment tool overlay by installing Graph-Tipper's OpenCode tool into the sandbox image and enabling it per-condition, with the GT host path supplied once via a UI/CLI-editable, gitignored machine-local registry (`{lib:NAME}`).

**Architecture:** A new `abench/libraries.py` owns a machine-local `.abench.local.json` registry (`name → host path`) and a `{lib:NAME}` path resolver that composes with the existing `{env:NAME}`. The sandbox image gains an entrypoint that installs GT's `integrations/opencode/tools/*.ts` from the mounted GT into the container's global OpenCode tools dir. The runner discovers GT's shipped tool names from the resolved registry path and writes a per-condition `agent.<name>.tools` gating map (baseline disables every GT tool; the tool condition enables its subset). The picocli experiment migrates to this shape and `prepare.py` reads the registry too.

**Tech Stack:** Python 3.10+ (stdlib + pydantic), pytest, Docker, OpenCode 1.15.x, Bun/TypeScript (GT tool, unchanged).

**Scope note (decomposition):** This plan is the bench-first **backend + container** mechanism — fully working and testable on its own (CLI + container runs need zero env vars). The web-UI "Libraries" panel (FastAPI `/api/libraries` + React) is a **separate follow-up plan** that consumes `abench/libraries.py`; it is intentionally out of scope here.

---

## File Structure

**New files**
- `abench/libraries.py` — registry load/save, `{lib:}` resolution, GT tool discovery. One responsibility: machine-local library paths + path-ref resolution.
- `docker/sandbox-entrypoint.sh` — installs GT OpenCode tools from the mounted GT, then `exec "$@"`.
- `.abench.local.example.json` — committed example of the registry shape.
- `tests/test_libraries.py` — unit tests for the registry + resolver + discovery.
- `tests/test_opencode_config_gating.py` — unit tests for the per-condition tools map.

**Modified files**
- `abench/opencode_client.py` — `build_opencode_config` gains `agent_tools`; `build_run_command` resolves `{lib:}`; `run_task` (Protocol + Real) threads `agent_tools`.
- `abench/runner.py` — pre-flight also checks `{lib:}`; `_run_one` computes + passes the per-condition tools map.
- `abench/config.py` — `Condition.tools`; `OpenCodeCfg.tools_lib`.
- `abench/cli.py` — `abench lib` subcommand.
- `abench_ui/run_session.py` — `_PerRunPublishingClient.run_task` forwards `agent_tools`.
- `tests/fakes.py`, `tests/test_runner.py` — fake clients accept `agent_tools`.
- `docker/Dockerfile.sandbox` — set up tools dir + `ENTRYPOINT`.
- `.gitignore` — add `.abench.local.json`.
- `experiments/picocli-putValue/experiment.yaml`, `experiment-tool-smoke.yaml`, `prepare.py`, and `overlays/impact/` → `overlays/impact-artifacts/`.

---

## Task 1: Library registry module — load + locate

**Files:**
- Create: `abench/libraries.py`
- Test: `tests/test_libraries.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_libraries.py
import json
from pathlib import Path

from abench import libraries


def test_load_registry_from_explicit_file(tmp_path, monkeypatch):
    f = tmp_path / ".abench.local.json"
    f.write_text(json.dumps({"libraries": {"graph-tipper": "/opt/gt"}}))
    monkeypatch.setenv(libraries.ENV_OVERRIDE, str(f))
    assert libraries.load_registry() == {"graph-tipper": "/opt/gt"}


def test_load_registry_walks_up_from_start(tmp_path, monkeypatch):
    monkeypatch.delenv(libraries.ENV_OVERRIDE, raising=False)
    (tmp_path / ".abench.local.json").write_text(
        json.dumps({"libraries": {"x": "/p"}}))
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    assert libraries.load_registry(start=deep) == {"x": "/p"}


def test_load_registry_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.delenv(libraries.ENV_OVERRIDE, raising=False)
    assert libraries.load_registry(start=tmp_path) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_libraries.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'abench.libraries'`.

- [ ] **Step 3: Write minimal implementation**

```python
# abench/libraries.py
"""Machine-local library registry (.abench.local.json) + {lib:NAME} resolution.

The registry maps a logical library name to its HOST path (e.g. where
Graph-Tipper is checked out). It is gitignored and machine-specific — the
UI/CLI edit it, the runner reads it — so experiment YAML stays portable and no
OS env var is needed to point at a local tool. See [[picocli-ab-pipeline-state]].
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ENV_OVERRIDE = "ABENCH_LOCAL_CONFIG"
FILENAME = ".abench.local.json"


def find_registry_file(start: Path | None = None) -> Path | None:
    """Locate the registry file: the ABENCH_LOCAL_CONFIG override if set, else
    the nearest .abench.local.json walking up from `start` (cwd by default)."""
    override = os.environ.get(ENV_OVERRIDE)
    if override:
        p = Path(override)
        return p if p.is_file() else None
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        cand = d / FILENAME
        if cand.is_file():
            return cand
    return None


def load_registry(start: Path | None = None) -> dict[str, str]:
    """Return the {name: host_path} map, or {} if there is no registry file."""
    f = find_registry_file(start)
    if f is None:
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    libs = data.get("libraries") if isinstance(data, dict) else None
    return libs if isinstance(libs, dict) else {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_libraries.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add abench/libraries.py tests/test_libraries.py
git commit -m "feat(libraries): machine-local .abench.local.json registry loader"
```

---

## Task 2: `{lib:NAME}` resolver (composes with `{env:}`)

**Files:**
- Modify: `abench/libraries.py`
- Test: `tests/test_libraries.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_libraries.py
import pytest


def test_resolve_lib_ref(tmp_path, monkeypatch):
    f = tmp_path / ".abench.local.json"
    f.write_text(json.dumps({"libraries": {"graph-tipper": "/opt/gt"}}))
    monkeypatch.setenv(libraries.ENV_OVERRIDE, str(f))
    out = libraries.resolve_path_refs("{lib:graph-tipper}:/opt/graph-tipper:ro")
    assert out == "/opt/gt:/opt/graph-tipper:ro"


def test_resolve_mixes_lib_and_env(tmp_path, monkeypatch):
    f = tmp_path / ".abench.local.json"
    f.write_text(json.dumps({"libraries": {"gt": "/opt/gt"}}))
    monkeypatch.setenv(libraries.ENV_OVERRIDE, str(f))
    monkeypatch.setenv("HOME", "/home/me")
    assert libraries.resolve_path_refs("{lib:gt}:{env:HOME}/.g") == "/opt/gt:/home/me/.g"


def test_resolve_missing_lib_raises_with_hint(tmp_path, monkeypatch):
    monkeypatch.delenv(libraries.ENV_OVERRIDE, raising=False)
    with pytest.raises(ValueError) as ei:
        libraries.resolve_path_refs("{lib:graph-tipper}:/x", start=tmp_path)
    msg = str(ei.value)
    assert "graph-tipper" in msg and ".abench.local.json" in msg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_libraries.py -k resolve -q`
Expected: FAIL — `AttributeError: module 'abench.libraries' has no attribute 'resolve_path_refs'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to abench/libraries.py
import re

from .envutil import expand_env_refs

# Library names may contain hyphens/dots (registry keys), unlike env var names.
_LIB_REF = re.compile(r"\{lib:([A-Za-z_][A-Za-z0-9_.\-]*)\}")


def resolve_path_refs(value: str, *, start: Path | None = None) -> str:
    """Resolve {lib:NAME} (from the registry) then {env:NAME} (from os.environ).

    {lib:NAME} that is not in the registry raises ValueError naming the library
    and where to add it — so a missing local path is as actionable as a missing
    env var (see runner pre-flight)."""
    registry = load_registry(start)
    src = find_registry_file(start)

    def sub(m: re.Match) -> str:
        name = m.group(1)
        if name not in registry:
            where = str(src) if src else f"a {FILENAME} file (none found)"
            raise ValueError(
                f"library '{name}' referenced as {{lib:{name}}} is not in the "
                f"registry ({where}). Add it with: abench lib add {name} <path>"
            )
        return registry[name]

    return expand_env_refs(_LIB_REF.sub(sub, value))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_libraries.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add abench/libraries.py tests/test_libraries.py
git commit -m "feat(libraries): {lib:NAME} path resolver composing with {env:}"
```

---

## Task 3: Discover GT's shipped OpenCode tool names

**Files:**
- Modify: `abench/libraries.py`
- Test: `tests/test_libraries.py`

The gated-tool universe is whatever GT ships in `integrations/opencode/tools/*.ts`
(the same files the image entrypoint installs). Discovering it from the resolved
host path keeps baseline gating drift-proof: if GT adds a tool, baseline disables
it automatically.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_libraries.py
def test_discover_opencode_tools(tmp_path):
    tools = tmp_path / "integrations" / "opencode" / "tools"
    tools.mkdir(parents=True)
    (tools / "impact.ts").write_text("export default {}")
    (tools / "crash_slice.ts").write_text("export default {}")
    (tools / "README.md").write_text("not a tool")
    assert libraries.discover_opencode_tools(tmp_path) == ["crash_slice", "impact"]


def test_discover_opencode_tools_missing_dir(tmp_path):
    assert libraries.discover_opencode_tools(tmp_path) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_libraries.py -k discover -q`
Expected: FAIL — `AttributeError: ... has no attribute 'discover_opencode_tools'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to abench/libraries.py
def discover_opencode_tools(lib_path: str | Path) -> list[str]:
    """Sorted tool names GT ships at <lib_path>/integrations/opencode/tools/*.ts
    (the OpenCode tool name is the filename stem). [] if the dir is absent."""
    tools_dir = Path(lib_path) / "integrations" / "opencode" / "tools"
    if not tools_dir.is_dir():
        return []
    return sorted(p.stem for p in tools_dir.glob("*.ts"))


def lib_names_in(value: str) -> list[str]:
    """The {lib:NAME} names referenced in a string (DRY: the one regex lives
    here; the runner pre-flight reuses this instead of duplicating it)."""
    return _LIB_REF.findall(value)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_libraries.py -q`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add abench/libraries.py tests/test_libraries.py
git commit -m "feat(libraries): discover GT's shipped OpenCode tool names"
```

---

## Task 4: Resolve `{lib:}` in container cache mounts

**Files:**
- Modify: `abench/opencode_client.py:257-258` (the `cache_mounts` loop in `build_run_command`)
- Test: `tests/test_opencode_client.py` (create if absent)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_opencode_client.py
import json

from abench.config import OpenCodeCfg, SandboxCfg
from abench.opencode_client import build_run_command


def test_build_run_command_resolves_lib_mount(tmp_path, monkeypatch):
    reg = tmp_path / ".abench.local.json"
    reg.write_text(json.dumps({"libraries": {"graph-tipper": "/host/gt"}}))
    monkeypatch.setenv("ABENCH_LOCAL_CONFIG", str(reg))
    cfg = OpenCodeCfg(sandbox=SandboxCfg(
        mode="container",
        cache_mounts=["{lib:graph-tipper}:/opt/graph-tipper:ro"]))
    argv = build_run_command(cfg, workdir="/w", model="m",
                             user_message="go", config_data={})
    assert "/host/gt:/opt/graph-tipper:ro" in argv
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_opencode_client.py -q`
Expected: FAIL — argv contains the literal `{lib:graph-tipper}:...` (or raises), not the resolved path.

- [ ] **Step 3: Write minimal implementation**

In `abench/opencode_client.py`, change the import and the cache-mounts loop.

Replace the import line:
```python
from .envutil import expand_env_refs
```
with:
```python
from .libraries import resolve_path_refs
```

Replace the loop (currently lines ~257-258):
```python
    for mount in sb.cache_mounts:
        argv += ["-v", expand_env_refs(mount)]
```
with:
```python
    for mount in sb.cache_mounts:
        argv += ["-v", resolve_path_refs(mount)]
```

(`resolve_path_refs` handles both `{lib:}` and `{env:}`, so existing `{env:}` mounts keep working.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_opencode_client.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add abench/opencode_client.py tests/test_opencode_client.py
git commit -m "feat(opencode): resolve {lib:} (and {env:}) in container cache mounts"
```

---

## Task 5: Pre-flight also checks `{lib:}` references

**Files:**
- Modify: `abench/runner.py` (`_required_env_refs`, `_preflight_env`)
- Test: `tests/test_runner_env_preflight.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_runner_env_preflight.py
def test_preflight_reports_missing_lib(tmp_path, monkeypatch):
    monkeypatch.delenv("ABENCH_LOCAL_CONFIG", raising=False)
    monkeypatch.setenv("ABENCH_LOCAL_CONFIG", str(tmp_path / "nope.json"))
    exp = _exp(
        tmp_path,
        sandbox=SandboxCfg(
            mode="container",
            cache_mounts=["{lib:graph-tipper}:/opt/graph-tipper:ro"]),
    )

    def _factory(_e):
        raise AssertionError("client built despite missing library path")

    import pytest
    with pytest.raises(RuntimeError) as ei:
        run_experiment(exp, _factory)
    assert "graph-tipper" in str(ei.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_runner_env_preflight.py -k missing_lib -q`
Expected: FAIL — no RuntimeError (the `{lib:}` ref is not yet pre-flighted; it would only blow up later in `build_run_command`).

- [ ] **Step 3: Write minimal implementation**

In `abench/runner.py`, add a `{lib:}` collector and extend `_preflight_env`.

Add this collector (it reuses `libraries.lib_names_in` from Task 3 — no second
copy of the regex):
```python
def _required_lib_refs(exp: Experiment) -> dict[str, list[str]]:
    """{lib:NAME} references the run needs resolved from the local registry.
    Mirrors _required_env_refs but for library paths (cache_mounts, overlay_env)."""
    from . import libraries

    refs: dict[str, list[str]] = {}

    def add(name: str, where: str) -> None:
        slots = refs.setdefault(name, [])
        if where not in slots:
            slots.append(where)

    if exp.opencode.sandbox.mode == "container":
        for mount in exp.opencode.sandbox.cache_mounts:
            for name in libraries.lib_names_in(mount):
                add(name, "sandbox.cache_mounts")
    for key, value in exp.overlay_env.items():
        for name in libraries.lib_names_in(value):
            add(name, f"overlay_env[{key}]")
    return refs
```

Then, inside `_preflight_env`, after the existing env-var `missing` block (before `return` when nothing is missing), add a library check. Replace the body of `_preflight_env` with:
```python
def _preflight_env(exp: Experiment) -> None:
    """Raise a single, oriented error if any required host env var OR local
    library path is missing — BEFORE the slow startup or any run."""
    from . import libraries

    refs = _required_env_refs(exp)
    missing_env = {n: w for n, w in refs.items() if not os.environ.get(n)}

    lib_refs = _required_lib_refs(exp)
    registry = libraries.load_registry()
    missing_lib = {n: w for n, w in lib_refs.items() if n not in registry}

    if not missing_env and not missing_lib:
        return

    parts: list[str] = []
    if missing_env:
        lines = "\n".join(
            f"  - {n}  (used by {', '.join(w)})" for n, w in sorted(missing_env.items()))
        example = " ".join(f"{n}=..." for n in sorted(missing_env))
        parts.append(
            "Missing required environment variable(s):\n" + lines + "\n\n"
            "These are OS environment variables read from the process running "
            "abench — export them in the shell that launches `abench`/`abench-ui` "
            "(NOT the web UI). Example:\n"
            f"  {example} abench run <experiment.yaml>")
    if missing_lib:
        lines = "\n".join(
            f"  - {n}  (used by {', '.join(w)})" for n, w in sorted(missing_lib.items()))
        adds = "\n".join(f"  abench lib add {n} <path>" for n in sorted(missing_lib))
        parts.append(
            "Missing local library path(s) in the registry "
            f"({libraries.FILENAME}):\n" + lines + "\n\nRegister them once:\n" + adds)
    raise RuntimeError("\n\n".join(parts))
```

- [ ] **Step 4: Run the full pre-flight + libraries suites**

Run: `python3 -m pytest tests/test_runner_env_preflight.py tests/test_libraries.py -q`
Expected: PASS (existing env tests + the new lib test).

- [ ] **Step 5: Commit**

```bash
git add abench/runner.py tests/test_runner_env_preflight.py
git commit -m "feat(runner): pre-flight also checks {lib:} paths against the registry"
```

---

## Task 6: Config — `Condition.tools` and `OpenCodeCfg.tools_lib`

**Files:**
- Modify: `abench/config.py` (the `Condition` and `OpenCodeCfg` classes)
- Test: `tests/test_config_tools.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config_tools.py
from abench.config import Condition, OpenCodeCfg


def test_condition_tools_defaults_empty():
    assert Condition(name="baseline").tools == []


def test_condition_tools_listed():
    c = Condition(name="aug", tools=["impact"])
    assert c.tools == ["impact"]


def test_opencode_tools_lib_default_none():
    assert OpenCodeCfg().tools_lib is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_config_tools.py -q`
Expected: FAIL — `Condition` has no `tools` / `OpenCodeCfg` has no `tools_lib`.

- [ ] **Step 3: Write minimal implementation**

In `abench/config.py`, add to `Condition` (after the `overlay` field):
```python
    tools: list[str] = Field(
        default_factory=list,
        title="Enabled tools",
        description=(
            "OpenCode tool names this condition enables (e.g. ['impact']). Tools "
            "shipped by opencode.tools_lib that are NOT listed are disabled for "
            "this condition's agent — so baseline (tools: []) never sees them, "
            "preserving the A/B contrast."
        ),
    )
```

In `abench/config.py`, add to `OpenCodeCfg` (after the `providers` field):
```python
    tools_lib: str | None = Field(
        default=None,
        title="Tools library",
        description=(
            "Registry library name whose integrations/opencode/tools/*.ts define "
            "the gateable tool universe. The runner disables, per condition, every "
            "such tool not in the condition's `tools` list. None = no GT tools."
        ),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_config_tools.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add abench/config.py tests/test_config_tools.py
git commit -m "feat(config): Condition.tools + OpenCodeCfg.tools_lib for per-condition gating"
```

---

## Task 7: Per-condition tool gating end-to-end

**Files:**
- Modify: `abench/opencode_client.py` (`build_opencode_config`, `OpenCodeClient` Protocol, `RealOpenCodeClient.run_task`)
- Modify: `abench/runner.py` (`_run_one` computes + passes the tools map)
- Modify: `tests/fakes.py`, `tests/test_runner.py`, `abench_ui/run_session.py` (accept/forward `agent_tools`)
- Test: `tests/test_opencode_config_gating.py`, plus an assertion in `tests/test_runner.py`

### 7a — `build_opencode_config` writes the agent tools map

- [ ] **Step 1: Write the failing test**

```python
# tests/test_opencode_config_gating.py
from abench.config import OpenCodeCfg
from abench.opencode_client import build_opencode_config


def test_agent_tools_injected_when_provided():
    cfg = OpenCodeCfg(agent="abench")
    out = build_opencode_config(cfg, "m", "sys", agent_tools={"impact": False})
    assert out["agent"]["abench"]["tools"] == {"impact": False}


def test_no_tools_key_when_none():
    cfg = OpenCodeCfg(agent="abench")
    out = build_opencode_config(cfg, "m", "sys")
    assert "tools" not in out["agent"]["abench"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_opencode_config_gating.py -q`
Expected: FAIL — `build_opencode_config() got an unexpected keyword argument 'agent_tools'`.

- [ ] **Step 3: Write minimal implementation**

In `abench/opencode_client.py`, change the signature and the agent block of `build_opencode_config`:
```python
def build_opencode_config(
    cfg: OpenCodeCfg,
    model: str,
    system_prompt: str,
    agent_tools: dict[str, bool] | None = None,
) -> dict:
```
And where the agent block is built (currently `"agent": {cfg.agent: {"prompt": system_prompt, "model": model}}`), replace with:
```python
    agent_block: dict = {"prompt": system_prompt, "model": model}
    if agent_tools:
        agent_block["tools"] = agent_tools
    config: dict = {
        "$schema": "https://opencode.ai/config.json",
        "model": model,
        "small_model": small,
        "agent": {cfg.agent: agent_block},
    }
```
(Delete the old `config` literal that hard-coded the agent block.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_opencode_config_gating.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add abench/opencode_client.py tests/test_opencode_config_gating.py
git commit -m "feat(opencode): build_opencode_config accepts per-agent tools map"
```

### 7b — Thread `agent_tools` through `run_task`

- [ ] **Step 6: Update the Protocol + RealOpenCodeClient**

In `abench/opencode_client.py`, add `agent_tools` to the `OpenCodeClient` Protocol's `run_task` signature and to `RealOpenCodeClient.run_task`, both as:
```python
        agent_tools: "dict[str, bool] | None" = None,
```
(place it just before `on_event` in each signature).

In `RealOpenCodeClient.run_task`, pass it into the config build (currently `config_data = build_opencode_config(self._cfg, model, system_prompt)`):
```python
        config_data = build_opencode_config(
            self._cfg, model, system_prompt, agent_tools=agent_tools
        )
```

- [ ] **Step 7: Update fakes to accept the kwarg**

In `tests/fakes.py`, add `agent_tools=None,` to `FakeOpenCodeClient.run_task` (before `on_event`).

In `tests/test_runner.py`, add `agent_tools=None,` to the `run_task` signatures of `_ServiceErrorClient`, `_CapturingClient`, and `_CancelAfterFirstClient` (before `on_event`).

In `abench_ui/run_session.py`, add `agent_tools=None,` to `_PerRunPublishingClient.run_task` (before `on_event`) and forward it in the inner call (`self._inner.run_task(... )` → add `agent_tools=agent_tools,`).

- [ ] **Step 8: Run the client + runner + UI suites**

Run: `python3 -m pytest tests/test_opencode_client.py tests/test_runner.py tests/test_opencode_config_gating.py -q`
Expected: PASS (signatures compatible).

- [ ] **Step 9: Commit**

```bash
git add abench/opencode_client.py tests/fakes.py tests/test_runner.py abench_ui/run_session.py
git commit -m "feat(opencode): thread agent_tools through run_task (Protocol + impls)"
```

### 7c — Runner computes the per-condition disable map

- [ ] **Step 10: Write the failing test**

```python
# add to tests/test_runner.py
def test_baseline_disables_gated_tools(tmp_path, monkeypatch):
    """With tools_lib set, baseline (tools=[]) disables every GT tool; the
    captured agent_tools map proves the gate."""
    import json
    from abench.config import (Condition, Experiment, MetricsCfg,
                               OpenCodeCfg, SandboxCfg)
    from abench.opencode_client import RunResult
    from abench.trace_model import Trace

    # Fake GT checkout shipping two tools.
    gt = tmp_path / "gt"
    (gt / "integrations" / "opencode" / "tools").mkdir(parents=True)
    for t in ("impact", "crash_slice"):
        (gt / "integrations" / "opencode" / "tools" / f"{t}.ts").write_text("x")
    reg = tmp_path / ".abench.local.json"
    reg.write_text(json.dumps({"libraries": {"graph-tipper": str(gt)}}))
    monkeypatch.setenv("ABENCH_LOCAL_CONFIG", str(reg))

    fixture = tmp_path / "fix"; fixture.mkdir(); (fixture / "a.py").write_text("x=1\n")
    reference = tmp_path / "ref"; reference.mkdir()

    captured = {}

    class _CaptureTools:
        def run_task(self, *, workdir, system_prompt, model, user_message,
                     timeout_s, agent_tools=None, on_event, log_sink=None,
                     debug_sink=None, cancel_event=None):
            captured["tools"] = agent_tools
            on_event({"type": "message.start"})
            return RunResult(trace=Trace(started_at=0.0, ended_at=1.0, finished=True),
                             raw_session=None)

    exp = Experiment(
        name="gate", fixture_path=fixture, reference_path=reference,
        task_prompt="t", system_prompt="s", model="m",
        output_dir=tmp_path / "runs", repetitions=1,
        conditions=[Condition(name="baseline", tools=[])],
        opencode=OpenCodeCfg(tools_lib="graph-tipper",
                             sandbox=SandboxCfg(mode="none")),
        metrics=MetricsCfg())
    exp.isolation.shuffle_order = False
    exp.verify.enabled = False
    run_experiment(exp, lambda e: _CaptureTools())
    assert captured["tools"] == {"crash_slice": False, "impact": False}
```

- [ ] **Step 11: Run test to verify it fails**

Run: `python3 -m pytest tests/test_runner.py -k baseline_disables -q`
Expected: FAIL — `captured["tools"]` is `None` (runner does not compute/pass the map yet).

- [ ] **Step 12: Write minimal implementation**

In `abench/runner.py`, add a helper near the other module helpers:
```python
def _agent_tools_for(exp: Experiment, cond: Condition) -> dict[str, bool] | None:
    """Per-condition OpenCode agent tools map: disable every tool the tools_lib
    ships that this condition does NOT enable. None when no tools_lib is set."""
    if not exp.opencode.tools_lib:
        return None
    from . import libraries
    registry = libraries.load_registry()
    lib_path = registry.get(exp.opencode.tools_lib)
    if not lib_path:
        return None  # pre-flight already reported a missing {lib:} path
    universe = libraries.discover_opencode_tools(lib_path)
    enabled = set(cond.tools)
    gate = {name: (name in enabled) for name in universe}
    return gate or None
```

In `_run_one`, locate the `client.run_task(` call and add the computed map. Just before the call, compute:
```python
        agent_tools = _agent_tools_for(exp, cond)
```
and add `agent_tools=agent_tools,` to the `client.run_task(...)` keyword arguments (e.g. right after `timeout_s=exp.timeout_s,`).

- [ ] **Step 13: Run test to verify it passes**

Run: `python3 -m pytest tests/test_runner.py -k baseline_disables -q`
Expected: PASS.

- [ ] **Step 14: Run the whole affected suite**

Run: `python3 -m pytest tests/test_runner.py tests/test_libraries.py tests/test_opencode_config_gating.py tests/test_runner_env_preflight.py -q`
Expected: PASS.

- [ ] **Step 15: Commit**

```bash
git add abench/runner.py tests/test_runner.py
git commit -m "feat(runner): compute + pass per-condition tool gating map"
```

---

## Task 8: Sandbox image installs GT tools (entrypoint)

**Files:**
- Create: `docker/sandbox-entrypoint.sh`
- Modify: `docker/Dockerfile.sandbox`

This task is integration-level; verification is a documented docker build + one-shot run (no unit test).

- [ ] **Step 1: Write the entrypoint script**

```bash
# docker/sandbox-entrypoint.sh
#!/bin/sh
# Install Graph-Tipper's OpenCode tools from the mounted GT into the container's
# global OpenCode tools dir, so the model can use them (gating is decided per
# run via the workdir opencode.json). No-op when GT is not mounted.
set -eu
GT_TOOLS="/opt/graph-tipper/integrations/opencode/tools"
DEST="/root/.config/opencode/tools"
if [ -d "$GT_TOOLS" ]; then
    mkdir -p "$DEST"
    n=0
    for f in "$GT_TOOLS"/*.ts; do
        [ -e "$f" ] || continue
        cp "$f" "$DEST/"; n=$((n + 1))
    done
    echo "[sandbox-entrypoint] installed $n GT OpenCode tool(s) into $DEST" >&2
fi
exec "$@"
```

- [ ] **Step 2: Wire it into the Dockerfile**

In `docker/Dockerfile.sandbox`, replace the final `WORKDIR /work` block with:
```dockerfile
# Install GT's OpenCode tools at container start from the mounted GT (no-op if
# GT isn't mounted). Keeps GT the single source of truth — no vendored copy.
COPY docker/sandbox-entrypoint.sh /usr/local/bin/sandbox-entrypoint.sh
RUN chmod +x /usr/local/bin/sandbox-entrypoint.sh

WORKDIR /work
ENTRYPOINT ["/usr/local/bin/sandbox-entrypoint.sh"]
```

- [ ] **Step 3: Build the image**

Run: `docker build -t abench-sandbox:latest -f docker/Dockerfile.sandbox .`
Expected: builds clean (extra-ca step prints its count; no errors).

- [ ] **Step 4: Verify the entrypoint installs tools from a mounted GT**

Run (replace `<GT>` with a real Graph-Tipper checkout):
```bash
docker run --rm -v <GT>:/opt/graph-tipper:ro abench-sandbox:latest \
  sh -lc 'ls /root/.config/opencode/tools/'
```
Expected: lists `impact.ts` (and `crash_slice.ts`), and stderr shows
`[sandbox-entrypoint] installed N GT OpenCode tool(s)`.

- [ ] **Step 5: Commit**

```bash
git add docker/sandbox-entrypoint.sh docker/Dockerfile.sandbox
git commit -m "feat(sandbox): entrypoint installs GT OpenCode tools from the mounted GT"
```

---

## Task 9: `abench lib` CLI command

**Files:**
- Modify: `abench/libraries.py` (add `save_library`)
- Modify: `abench/cli.py` (add the `lib` subcommand)
- Test: `tests/test_cli_lib.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_lib.py
import json

from abench.cli import main


def test_lib_add_then_list(tmp_path, monkeypatch, capsys):
    reg = tmp_path / ".abench.local.json"
    monkeypatch.setenv("ABENCH_LOCAL_CONFIG", str(reg))
    assert main(["lib", "add", "graph-tipper", "/opt/gt"]) == 0
    assert json.loads(reg.read_text())["libraries"]["graph-tipper"] == "/opt/gt"
    assert main(["lib", "list"]) == 0
    assert "graph-tipper" in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_cli_lib.py -q`
Expected: FAIL — `invalid choice: 'lib'` (subcommand absent).

- [ ] **Step 3: Add `save_library` to libraries.py**

```python
# add to abench/libraries.py
def registry_path(start: Path | None = None) -> Path:
    """Where to write the registry: the override, an existing file walking up,
    or `<cwd>/.abench.local.json` as the create-here default."""
    override = os.environ.get(ENV_OVERRIDE)
    if override:
        return Path(override)
    found = find_registry_file(start)
    return found if found is not None else (start or Path.cwd()) / FILENAME


def save_library(name: str, path: str, start: Path | None = None) -> Path:
    """Upsert one {name: path} into the registry, creating the file if needed.
    Returns the registry file path."""
    f = registry_path(start)
    data: dict = {}
    if f.is_file():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("libraries", {})
    data["libraries"][name] = path
    f.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return f
```

- [ ] **Step 4: Add the `lib` subcommand to cli.py**

In `abench/cli.py`, after the other `sub.add_parser(...)` blocks (before `args = parser.parse_args(argv)`), add:
```python
    lib_p = sub.add_parser("lib", help="manage the local library path registry")
    lib_sub = lib_p.add_subparsers(dest="lib_cmd", required=True)
    lib_add = lib_sub.add_parser("add", help="register/update a library path")
    lib_add.add_argument("name")
    lib_add.add_argument("path")
    lib_sub.add_parser("list", help="list registered library paths")
```
And after the `if args.cmd == "report":` handler (or alongside the other command handlers), add:
```python
    if args.cmd == "lib":
        from . import libraries
        if args.lib_cmd == "add":
            f = libraries.save_library(args.name, args.path)
            print(f"registered {args.name} -> {args.path} in {f}")
            return 0
        if args.lib_cmd == "list":
            reg = libraries.load_registry()
            if not reg:
                print("(no libraries registered)")
            for name, path in sorted(reg.items()):
                print(f"{name}\t{path}")
            return 0
        return 1
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_cli_lib.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add abench/libraries.py abench/cli.py tests/test_cli_lib.py
git commit -m "feat(cli): abench lib add/list for the local library registry"
```

---

## Task 10: Migrate the picocli experiment + prepare.py + gitignore

**Files:**
- Rename: `experiments/picocli-putValue/overlays/impact/` → `overlays/impact-artifacts/`
- Delete: `overlays/impact-artifacts/.opencode/tools/impact.ts`, `overlays/impact-artifacts/.opencode/impact.json.tmpl`
- Create: `overlays/impact-artifacts/.opencode/impact.json` (static)
- Modify: `experiments/picocli-putValue/experiment.yaml`, `experiment-tool-smoke.yaml`, `prepare.py`
- Modify: `.gitignore`
- Create: `.abench.local.example.json`

- [ ] **Step 1: Restructure the overlay**

```bash
cd experiments/picocli-putValue
git mv overlays/impact overlays/impact-artifacts
git rm overlays/impact-artifacts/.opencode/tools/impact.ts
git rm overlays/impact-artifacts/.opencode/impact.json.tmpl
```

Create `overlays/impact-artifacts/.opencode/impact.json` (static — the container
harness_path is the fixed mount; no env, no tmpl):
```json
{
  "harness_path": "/opt/graph-tipper",
  "methods": "../.impact/methods.json",
  "coverage": "../.impact/coverage.json",
  "mutation": "../.impact/mutation.json",
  "total_tests": 2234
}
```

- [ ] **Step 2: Update both experiment YAMLs**

In `experiment.yaml` and `experiment-tool-smoke.yaml`:
- Under `opencode:`, add `tools_lib: graph-tipper` and change the mount:
  ```yaml
  opencode:
    agent: abench
    tools_lib: graph-tipper
    providers: [ ... unchanged ... ]
    sandbox:
      mode: container
      cache_mounts:
        - "{lib:graph-tipper}:/opt/graph-tipper:ro"
        - "{env:HOME}/.gradle:/root/.gradle:ro"
  ```
- Delete the `overlay_env:` block entirely.
- In `conditions:`, give each condition a `tools` list and point the tool
  condition's overlay at the renamed dir. For `experiment.yaml`:
  ```yaml
  conditions:
    - {name: baseline,          augmentation: null, tools: []}
    - {name: augmented,         augmentation: ./slices/putValue-graph-slice.md, tools: []}
    - {name: augmented-verbose, augmentation: ./slices/putValue-graph-slice-verbose.md, tools: []}
    - name: augmented-tool
      augmentation: ./slices/impact-tool-briefing.md
      overlay: ./overlays/impact-artifacts
      tools: [impact]
  ```
  For `experiment-tool-smoke.yaml`, the single condition becomes:
  ```yaml
  conditions:
    - name: augmented-tool
      augmentation: ./slices/impact-tool-briefing.md
      overlay: ./overlays/impact-artifacts
      tools: [impact]
  ```

- [ ] **Step 3: Update prepare.py — drop the tool copy, read the registry, validate the static config**

In `experiments/picocli-putValue/prepare.py`:

(a) Replace the GT lookup (line ~23 `GT = os.environ.get("GRAPH_TIPPER_HOME")`) with a registry-first resolution:
```python
def _resolve_gt():
    """GT host path: local registry ('graph-tipper') first, then GRAPH_TIPPER_HOME."""
    try:
        from abench.libraries import load_registry
        p = load_registry().get("graph-tipper")
        if p:
            return p
    except Exception:
        pass
    return os.environ.get("GRAPH_TIPPER_HOME")

GT = _resolve_gt()
```
And update the deps-check message (line ~50-51) to mention either source:
```python
    if GT is None or not (Path(GT) / "harness" / "impact").is_dir():
        missing.append("Graph-Tipper path not found — set it with "
                       "`abench lib add graph-tipper <path>` or GRAPH_TIPPER_HOME")
```

(b) In `s_artifacts`, the `total_tests` validation reads the `.tmpl` (lines ~112-116).
Point it at the new static config instead:
```python
    cfg = json.loads((HERE / "overlays" / "impact-artifacts" / ".opencode" / "impact.json")
                     .read_text(encoding="utf-8"))
    if n != cfg["total_tests"]:
        print(f"[prepare:artifacts] WARNING: total_tests in impact.json={cfg['total_tests']} "
              f"but executed universe has {n} tests")
```
Also change the artifacts copy destination (line ~108) from `overlays/impact/.impact`
to `overlays/impact-artifacts/.impact`.

(c) Delete the `s_overlay` function (lines ~120-125) and remove `("overlay", s_overlay),`
from the stages list (line ~144). The tool is now installed by the image, not copied
into the overlay.

(d) Update the module docstring (line ~6) to drop the `GRAPH_TIPPER_HOME env` wording:
`Needs: activated venv, Graph-Tipper registered (abench lib add graph-tipper <path>) or GRAPH_TIPPER_HOME, JDK 21, opencode 1.15.x.`
And the stage list (line ~4): `Stages: deps -> fixtures -> artifacts -> smoke.`

- [ ] **Step 4: gitignore + example registry**

In `.gitignore`, retarget the two stale overlay lines to the renamed dir AND drop
the tool-glue ignore (the glue no longer lives in the overlay). Replace:
```
experiments/*/overlays/impact/.impact/
experiments/*/overlays/impact/.opencode/tools/
```
with (keep ignoring the regenerated artifacts; the static `.opencode/impact.json`
is intentionally NOT ignored — it is committed):
```
experiments/*/overlays/impact-artifacts/.impact/
```
Then append:
```
# machine-local library paths (never commit; per-machine)
.abench.local.json
```

Create `.abench.local.example.json`:
```json
{
  "libraries": {
    "graph-tipper": "/absolute/path/to/your/Graph-Tipper/checkout"
  }
}
```

- [ ] **Step 5: Validate the experiments load and the overlay is glue-free**

Run:
```bash
python3 -c "from abench.config import load_experiment as L; \
e=L('experiments/picocli-putValue/experiment.yaml'); \
print('tools_lib=', e.opencode.tools_lib); \
print('conds=', [(c.name, c.tools) for c in e.conditions])"
test ! -e experiments/picocli-putValue/overlays/impact-artifacts/.opencode/tools/impact.ts \
  && echo 'OK: no tool glue in overlay'
```
Expected: prints `tools_lib= graph-tipper`, the conditions with their `tools`
lists, and `OK: no tool glue in overlay`.

- [ ] **Step 6: Commit**

```bash
git add -A experiments/picocli-putValue .gitignore .abench.local.example.json
git commit -m "refactor(picocli): consume GT via installed tool + {lib:} registry, drop env/overlay glue"
```

---

## Task 11: Verification — upgraded risk-gate 18.3 (container smoke)

**Files:** none (operational verification on a machine with Docker + GT + a model key).

This replaces the old overlay-based smoke. Run it where Docker, a Graph-Tipper
checkout, and a working model key exist.

- [ ] **Step 1: Register GT once (no env var)**

```bash
abench lib add graph-tipper /path/to/Graph-Tipper
```

- [ ] **Step 2: Build the image (if not already built in Task 8)**

Run: `docker build -t abench-sandbox:latest -f docker/Dockerfile.sandbox .`

- [ ] **Step 3: Run the tool-smoke experiment with ZERO GT env var**

Run:
```bash
DEEPSEEK_API_KEY=sk-... HOME=$HOME \
  abench run experiments/picocli-putValue/experiment-tool-smoke.yaml
```
Expected: no "GRAPH_TIPPER_HOME is not set" / no missing-lib pre-flight error;
the run starts and the agent can call `impact`.

- [ ] **Step 4: Assert the tool worked and the gate is correct**

Inspect the newest run dir under `experiments/picocli-putValue/runs/.../augmented-tool/rep_0/`:
- `debug.log` shows the entrypoint line `installed N GT OpenCode tool(s)`.
- `trace.json` / `events.jsonl`: the `impact` tool was called and returned
  markdown (Tier-1/Tier-2/blind-spot sections), analyzing a NON-empty diff.
- The workdir `.opencode/impact.json` had `harness_path: /opt/graph-tipper` (constant).

- [ ] **Step 5: Assert baseline cleanliness (A/B integrity)**

Run a one-rep baseline (edit a temporary copy of the smoke YAML to a single
`{name: baseline, tools: []}` condition, or use the full `experiment.yaml`) and
confirm in its `events.jsonl`/`trace.json` that `impact` is **never listed or
called** — the gate disabled it. This is the core validity check the new design
must preserve.

- [ ] **Step 6: Full regression**

Run: `python3 -m pytest -q`
Expected: PASS across the suite.

---

## Self-review notes (addressed)

- **Spec §4.2.D A/B leak hazard:** handled by `_agent_tools_for` disabling the
  whole discovered universe (impact AND crash_slice) for non-enabling conditions;
  Task 7c test asserts both are `False` for baseline.
- **Spec §4.2.B image install:** entrypoint-from-mounted-GT (Task 8), GT stays the
  single source of truth; matches host-side discovery in Task 7c (same dir).
- **Spec §5 testing:** registry/resolver (Tasks 1-3), `{lib:}` in mounts (Task 4),
  pre-flight (Task 5), config builder gating (Task 7a), runner integration (Task 7c),
  container smoke (Task 11). UI endpoints/panel are the deferred follow-up plan.
- **Back-compat:** `{env:}` still resolves via `resolve_path_refs`; existing
  experiments using `{env:GRAPH_TIPPER_HOME}` keep working.
