# OpenCode custom-tool validation mechanism — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `validate_tool(...)` + an `abench validate-tool` CLI that report, model-free, whether an OpenCode custom tool loads and is offered to the agent in the bench's sandbox — and use it to diagnose+fix the container so `impact` registers.

**Architecture:** A new self-contained `abench/tool_validation.py` builds a throwaway opencode project (the tool under `.opencode/tools/` + a minimal `opencode.json`), runs `opencode debug agent <agent> --dir <workdir>` (in the container for `mode: container`, else on host), and parses the result: exit 0 → tool present in the resolved `.tools`; exit≠0 → build/transpile errors from stderr. No model, key, or network.

**Tech Stack:** Python 3.12 (stdlib: subprocess/tempfile/json/re/shutil/dataclasses), pytest, opencode 1.15.x CLI, Docker (container mode only).

**Ground truth (verified on opencode 1.15.11):** `opencode debug agent <name>` prints resolved-agent JSON with `"tools": {"<name>": true}` for a custom tool in `<dir>/.opencode/tools/<name>.ts`; a broken tool makes it exit non-zero with stderr `AggregateError: N errors building "<…>.ts"` and the tool absent from `.tools`. `.opencode/tools/` (plural) is correct; `@opencode-ai/plugin` resolves with no extra install.

---

## File Structure

- **Create `abench/tool_validation.py`** — one responsibility: validate one OpenCode custom tool in a given sandbox. Public: `ToolValidation` (dataclass), `validate_tool(...)`. Private helpers: `_parse_probe`, `_build_probe_workdir`, `_probe_command`.
- **Create `tests/test_tool_validation.py`** — unit tests for the three helpers + an orchestration test (mocked subprocess) + an integration test against real opencode (skipped if the binary is absent).
- **Modify `abench/cli.py`** — add the `validate-tool` subcommand + dispatch (mirrors the existing `lib` subcommand).
- **Modify `docker/Dockerfile.sandbox`** — Task 6, diagnosis-driven (e.g. pin opencode version) so `impact` registers in the container.

All commands below assume the implementation runs in a worktree with its own venv (`.venv/bin/python`) and `opencode` on PATH.

---

## Task 1: `ToolValidation` + `_parse_probe` (output parser)

**Files:**
- Create: `abench/tool_validation.py`
- Test: `tests/test_tool_validation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tool_validation.py
import json

from abench.tool_validation import ToolValidation, _parse_probe


def test_parse_registered_when_tool_truthy_in_tools():
    out = json.dumps({"name": "abench", "tools": {"impact": True, "bash": True}})
    r = _parse_probe("impact", 0, out, "")
    assert isinstance(r, ToolValidation)
    assert r.registered is True
    assert r.errors == []
    assert r.tool_name == "impact"


def test_parse_not_registered_when_absent():
    out = json.dumps({"tools": {"bash": True}})
    r = _parse_probe("impact", 0, out, "")
    assert r.registered is False
    assert r.errors  # a human-readable "not present" message


def test_parse_build_error_on_nonzero_exit():
    stderr = ('ERROR 2026-06-15 service=default name=AggregateError '
              'message=4 errors building "/x/.opencode/tools/impact.ts" '
              'stack=AggregateError: 4 errors building "/x/.opencode/tools/impact.ts"')
    r = _parse_probe("impact", 1, "", stderr)
    assert r.registered is False
    assert r.exit_code == 1
    assert any("errors building" in e for e in r.errors)


def test_parse_unparseable_stdout_is_not_registered():
    r = _parse_probe("impact", 0, "not json", "")
    assert r.registered is False
    assert r.errors
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_tool_validation.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'abench.tool_validation'`.

- [ ] **Step 3: Write minimal implementation**

```python
# abench/tool_validation.py
"""Validate that an OpenCode custom tool loads and is offered to the agent.

Model-free: runs `opencode debug agent <agent>` (which transpiles the tool and
prints the resolved agent config incl. its `tools` map) in the bench's sandbox.
No API key / network needed, so a restrictive network does not interfere.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

# Matches opencode's build-failure summary, e.g.
#   4 errors building "/work/.opencode/tools/impact.ts"
_BUILD_ERR = re.compile(r'\d+ errors? building "[^"]+"')


@dataclass
class ToolValidation:
    tool_name: str
    registered: bool
    errors: list[str] = field(default_factory=list)
    exit_code: int = 0
    raw: str = ""


def _parse_probe(tool_name: str, exit_code: int, stdout: str, stderr: str) -> ToolValidation:
    """Interpret an `opencode debug agent` result.

    exit 0  → stdout is the resolved-agent JSON; registered iff the tool appears
              truthy under `.tools`.
    exit !=0 → the probe failed (commonly the tool did not transpile); surface
               the build-error summary line(s) from stderr.
    """
    if exit_code == 0:
        try:
            data = json.loads(stdout)
            tools = data.get("tools") or {}
            registered = bool(tools.get(tool_name))
        except (json.JSONDecodeError, AttributeError):
            return ToolValidation(
                tool_name, False,
                ["opencode debug agent produced unparseable output"],
                exit_code, stdout)
        errors = [] if registered else [
            f"tool '{tool_name}' is not present in the agent's resolved tools"]
        return ToolValidation(tool_name, registered, errors, exit_code, stdout)

    errs = _BUILD_ERR.findall(stderr)
    if not errs:
        tail = [ln for ln in stderr.strip().splitlines() if ln.strip()][-3:]
        errs = tail or ["opencode debug agent failed (no diagnostic output)"]
    return ToolValidation(tool_name, False, errs, exit_code, stdout)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_tool_validation.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add abench/tool_validation.py tests/test_tool_validation.py
git commit -m "feat(tool-validation): ToolValidation + debug-agent output parser"
```

---

## Task 2: `_build_probe_workdir`

**Files:**
- Modify: `abench/tool_validation.py`
- Test: `tests/test_tool_validation.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_tool_validation.py
import json
from pathlib import Path

from abench.tool_validation import _build_probe_workdir


def test_build_probe_workdir_lays_out_tool_and_config(tmp_path):
    tool = tmp_path / "echofile.ts"
    tool.write_text("export default {}\n")
    dest = tmp_path / "probe"
    out = _build_probe_workdir(tool, "abench", "deepseek/deepseek-chat", dest)
    assert out == dest
    copied = dest / ".opencode" / "tools" / "echofile.ts"
    assert copied.is_file()
    cfg = json.loads((dest / "opencode.json").read_text())
    assert "abench" in cfg["agent"]
    assert cfg["agent"]["abench"]["model"] == "deepseek/deepseek-chat"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_tool_validation.py -k build_probe_workdir -q`
Expected: FAIL — `cannot import name '_build_probe_workdir'`.

- [ ] **Step 3: Write minimal implementation**

Add to `abench/tool_validation.py` (imports `json` already present; add `shutil` and `Path`):

```python
import shutil
from pathlib import Path


def _build_probe_workdir(tool_src: Path, agent: str, model: str, dest: Path) -> Path:
    """Lay out a minimal opencode project under `dest`: the tool at
    `.opencode/tools/<name>.ts` plus an `opencode.json` defining `agent`.
    `model` is only for agent-config resolution — the probe never calls it."""
    tools_dir = dest / ".opencode" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(tool_src, tools_dir / tool_src.name)
    config = {
        "$schema": "https://opencode.ai/config.json",
        "agent": {agent: {"prompt": "tool-validation probe", "model": model}},
    }
    (dest / "opencode.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    return dest
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_tool_validation.py -k build_probe_workdir -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add abench/tool_validation.py tests/test_tool_validation.py
git commit -m "feat(tool-validation): build minimal probe workdir"
```

---

## Task 3: `_probe_command` (host vs container argv)

**Files:**
- Modify: `abench/tool_validation.py`
- Test: `tests/test_tool_validation.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_tool_validation.py
from abench.config import SandboxCfg
from abench.tool_validation import _probe_command


def test_probe_command_host_mode():
    cmd = _probe_command(SandboxCfg(mode="none"), "/tmp/probe", "abench")
    assert cmd[:4] == ["opencode", "debug", "agent", "abench"]
    assert "--dir" in cmd and "/tmp/probe" in cmd
    assert "docker" not in cmd and "run" not in cmd[:2]


def test_probe_command_container_mode_wraps_docker():
    sb = SandboxCfg(mode="container", image="abench-sandbox:latest",
                    runtime="docker", workdir_mount="/work")
    cmd = _probe_command(sb, "/tmp/probe", "abench")
    assert cmd[:3] == ["docker", "run", "--rm"]
    assert "-v" in cmd and "/tmp/probe:/work" in cmd
    assert "abench-sandbox:latest" in cmd
    # inner command targets the in-container mount, not the host path
    assert "opencode" in cmd and "/work" in cmd
    assert "/tmp/probe" not in cmd[cmd.index("abench-sandbox:latest"):]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_tool_validation.py -k probe_command -q`
Expected: FAIL — `cannot import name '_probe_command'`.

- [ ] **Step 3: Write minimal implementation**

Add to `abench/tool_validation.py` (note: `SandboxCfg` is only needed as a type; import lazily to avoid a config import at module load — accept it structurally):

```python
def _probe_command(sandbox, workdir: str, agent: str) -> list[str]:
    """Argv to run `opencode debug agent` against `workdir`.

    Container mode wraps in `<runtime> run --rm` with ONLY the probe workdir
    mounted — no provider `-e` env and no cache mounts, because registration
    neither calls a model nor executes the tool body."""
    dir_arg = sandbox.workdir_mount if sandbox.mode == "container" else workdir
    inner = ["opencode", "debug", "agent", agent,
             "--dir", dir_arg, "--print-logs", "--log-level", "DEBUG"]
    if sandbox.mode != "container":
        return inner
    return [sandbox.runtime, "run", "--rm",
            "-v", f"{workdir}:{sandbox.workdir_mount}",
            "-w", sandbox.workdir_mount,
            sandbox.image, *inner]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_tool_validation.py -k probe_command -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add abench/tool_validation.py tests/test_tool_validation.py
git commit -m "feat(tool-validation): host/container probe command builder"
```

---

## Task 4: `validate_tool` orchestration

**Files:**
- Modify: `abench/tool_validation.py`
- Test: `tests/test_tool_validation.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_tool_validation.py
import shutil as _shutil
import subprocess
import pytest

from abench.tool_validation import validate_tool


def test_validate_tool_orchestration_mocked(tmp_path, monkeypatch):
    """validate_tool builds a workdir, runs the probe, and parses — without a
    real opencode (subprocess.run is stubbed)."""
    tool = tmp_path / "impact.ts"
    tool.write_text("export default {}\n")

    class _CP:
        returncode = 0
        stdout = json.dumps({"tools": {"impact": True}})
        stderr = ""

    seen = {}

    def fake_run(cmd, capture_output, text, timeout):
        seen["cmd"] = cmd
        return _CP()

    monkeypatch.setattr(subprocess, "run", fake_run)
    r = validate_tool(tool, sandbox=SandboxCfg(mode="none"), agent="abench")
    assert r.registered is True
    assert seen["cmd"][:4] == ["opencode", "debug", "agent", "abench"]


@pytest.mark.skipif(_shutil.which("opencode") is None, reason="opencode not on PATH")
def test_validate_tool_integration_good_and_broken(tmp_path):
    """Real opencode: a valid tool registers; a broken one does not."""
    good = tmp_path / "echo_probe.ts"
    good.write_text(
        'import { tool } from "@opencode-ai/plugin"\n'
        'export default tool({ description: "x", args: {}, '
        'async execute() { return "ok" } })\n')
    rg = validate_tool(good, sandbox=SandboxCfg(mode="none"), agent="abench")
    assert rg.registered is True, rg.errors

    bad = tmp_path / "broken_probe.ts"
    bad.write_text('import { tool } from "@opencode-ai/plugin"\n'
                   'export default tool({ this is not valid {{{\n')
    rb = validate_tool(bad, sandbox=SandboxCfg(mode="none"), agent="abench")
    assert rb.registered is False
    assert rb.errors
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_tool_validation.py -k validate_tool -q`
Expected: FAIL — `cannot import name 'validate_tool'`.

- [ ] **Step 3: Write minimal implementation**

Add to `abench/tool_validation.py` (add `import subprocess`, `import tempfile`):

```python
import subprocess
import tempfile


def validate_tool(tool_src, *, sandbox, agent: str = "abench",
                  model: str = "deepseek/deepseek-chat") -> ToolValidation:
    """Validate one OpenCode custom tool in `sandbox`. Returns a ToolValidation.

    Builds a throwaway opencode project containing only this tool, runs
    `opencode debug agent` against it (in the container for mode='container'),
    and reports whether the tool is registered + any load errors. The `model` is
    only for agent-config resolution; `debug agent` never calls it.
    """
    tool_src = Path(tool_src)
    tool_name = tool_src.stem
    with tempfile.TemporaryDirectory(prefix="abench-toolval-") as tmp:
        workdir = _build_probe_workdir(tool_src, agent, model, Path(tmp))
        cmd = _probe_command(sandbox, str(workdir), agent)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            return ToolValidation(tool_name, False,
                                  ["opencode debug agent timed out after 120s"], -1, "")
        except FileNotFoundError as exc:
            return ToolValidation(tool_name, False,
                                  [f"could not run probe: {exc}"], -1, "")
        return _parse_probe(tool_name, proc.returncode, proc.stdout, proc.stderr)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_tool_validation.py -q`
Expected: PASS. The integration test runs real `opencode debug agent` twice (good→registered, broken→not). If it errors because `debug agent` rejects the placeholder `model`, change the integration calls to pass the experiment's real model id and note it in `validate_tool`'s default; then re-run.

- [ ] **Step 5: Commit**

```bash
git add abench/tool_validation.py tests/test_tool_validation.py
git commit -m "feat(tool-validation): validate_tool orchestration (+ integration test)"
```

---

## Task 5: `abench validate-tool` CLI

**Files:**
- Modify: `abench/cli.py`
- Test: `tests/test_cli_validate_tool.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_validate_tool.py
from pathlib import Path

from abench.cli import main


def test_validate_tool_cli_reports_registered(tmp_path, monkeypatch, capsys):
    # Minimal experiment YAML (host sandbox, so no docker needed).
    exp = tmp_path / "exp.yaml"
    fixture = tmp_path / "fix"; fixture.mkdir(); (fixture / "a.py").write_text("x=1\n")
    ref = tmp_path / "ref"; ref.mkdir()
    exp.write_text(
        "name: t\n"
        f"fixture_path: {fixture}\n"
        f"reference_path: {ref}\n"
        "task_prompt: t\nsystem_prompt: s\nmodel: deepseek/deepseek-chat\n"
        f"output_dir: {tmp_path/'runs'}\n"
        "conditions: [{name: baseline}]\n"
        "opencode: {agent: abench, sandbox: {mode: none}}\n")
    tool = tmp_path / "mytool.ts"; tool.write_text("export default {}\n")

    # Stub validate_tool so the CLI test does not need a real opencode.
    import abench.tool_validation as tv
    from abench.tool_validation import ToolValidation
    monkeypatch.setattr(tv, "validate_tool",
                        lambda *a, **k: ToolValidation("mytool", True, [], 0, "{}"))

    rc = main(["validate-tool", str(exp), str(tool)])
    assert rc == 0
    assert "mytool" in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli_validate_tool.py -q`
Expected: FAIL — argparse `invalid choice: 'validate-tool'`.

- [ ] **Step 3: Write minimal implementation**

In `abench/cli.py`, add the parser near the other `sub.add_parser(...)` blocks:

```python
    vt_p = sub.add_parser(
        "validate-tool",
        help="check that an OpenCode custom tool loads in the experiment's sandbox")
    vt_p.add_argument("experiment", help="path to experiment YAML")
    vt_p.add_argument("tool", help="path to the tool .ts file")
```

And add a dispatch handler alongside the others (e.g. after the `lib` handler):

```python
    if args.cmd == "validate-tool":
        from .config import load_experiment
        from . import tool_validation
        exp = load_experiment(args.experiment)
        r = tool_validation.validate_tool(
            Path(args.tool), sandbox=exp.opencode.sandbox,
            agent=exp.opencode.agent, model=exp.model)
        if r.registered:
            print(f"✓ {r.tool_name} registered")
            return 0
        print(f"✗ {r.tool_name} NOT registered (exit {r.exit_code})")
        for e in r.errors:
            print(f"  - {e}")
        return 1
```

(The handler imports `tool_validation` lazily — the import must reference the module, not the function, so the test's `monkeypatch.setattr(tv, "validate_tool", ...)` is honoured.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_cli_validate_tool.py -q`
Expected: PASS.

- [ ] **Step 5: Run the whole tool-validation + cli suite**

Run: `.venv/bin/python -m pytest tests/test_tool_validation.py tests/test_cli_validate_tool.py tests/test_cli.py -q`
Expected: PASS (existing CLI commands unaffected).

- [ ] **Step 6: Commit**

```bash
git add abench/cli.py tests/test_cli_validate_tool.py
git commit -m "feat(cli): abench validate-tool <experiment> <tool.ts>"
```

---

## Task 6: Diagnose + fix the container so `impact` registers (operational, server)

**Files:** `docker/Dockerfile.sandbox` (the fix), once the cause is known.

No local docker on the dev machine — run on the server. Diagnosis-driven: the probe output names the cause.

- [ ] **Step 1: Build the sandbox image (server)**

Run: `docker build -t abench-sandbox:latest -f docker/Dockerfile.sandbox .`

- [ ] **Step 2: Probe `impact` inside the container**

Run (the experiment uses `mode: container`, so `validate-tool` runs the probe in the image):
```bash
abench validate-tool experiments/picocli-putValue/experiment-tool-smoke.yaml \
  /mnt/d/Projects/Graph-Tipper/integrations/opencode/tools/impact.ts
```
Expected to FAIL first: `✗ impact NOT registered` with the captured error (this reproduces the `bash impact` bug). Record the error text.

- [ ] **Step 3: Apply the matching Dockerfile fix**

Map the error to a fix in `docker/Dockerfile.sandbox`:
- version drift (most likely) — the host runs opencode 1.15.11 but the image's `npm install -g opencode-ai` is unpinned: pin it, e.g. `npm install -g opencode-ai@1.15.11` (replace the `npm install -g opencode-ai || curl …` line with the pinned install; keep a fallback only to the same pinned version).
- `@opencode-ai/plugin` not resolvable / Bun runtime missing — ensure the install method that bundles the plugin SDK + Bun is used (mirror the host's working install).
Rebuild: `docker build -t abench-sandbox:latest -f docker/Dockerfile.sandbox .`

- [ ] **Step 4: Re-probe — must be registered**

Run the Step 2 command again.
Expected: `✓ impact registered`.

- [ ] **Step 5: Confirm end-to-end (the original bug is gone)**

Run: `abench run experiments/picocli-putValue/experiment-tool-smoke.yaml`
Expected: the trace shows the agent calling the `impact` tool (a `[tool] … impact` line), NOT `bash … impact`.

- [ ] **Step 6: Commit the Dockerfile fix**

```bash
git add docker/Dockerfile.sandbox
git commit -m "fix(sandbox): pin opencode so custom tools register in the container"
```

---

## Self-review notes (addressed)

- **Spec §4.1 `validate_tool` / ToolValidation** → Tasks 1–4 (parser, workdir, command, orchestration). Signature/return match the spec (`{tool_name, registered, errors, exit_code, raw}`).
- **Spec §4.2 CLI** → Task 5 (`abench validate-tool <experiment> <tool.ts>`).
- **Spec §4.3 container fix** → Task 6 (diagnosis-driven; done-criterion `impact registered: true` + agent calls the tool).
- **Spec §6 testing** → unit (parser/workdir/command, Tasks 1–3), orchestration mocked + integration good/broken (Task 4), CLI (Task 5), container (Task 6).
- **Spec §7 open item (placeholder model):** Task 4 Step 4 explicitly verifies it and says what to change if `debug agent` rejects the model.
- **Type consistency:** `ToolValidation(tool_name, registered, errors, exit_code, raw)` and `validate_tool(tool_src, *, sandbox, agent, model)` are used identically across Tasks 1–5; `_build_probe_workdir(tool_src, agent, model, dest)` and `_probe_command(sandbox, workdir, agent)` match their call sites.
- **No placeholders:** every code/step is concrete. Task 6's specific Dockerfile edit is genuinely data-dependent (the probe reveals it) — the task gives the exact command to get that data and the most-likely fix with exact syntax.
