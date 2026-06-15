"""Validate that an OpenCode custom tool loads and is offered to the agent.

Model-free: runs `opencode debug agent <agent>` (which transpiles the tool and
prints the resolved agent config incl. its `tools` map) in the bench's sandbox.
No API key / network needed, so a restrictive network does not interfere.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

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
              truthy under ``.tools``.
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


def _build_probe_workdir(tool_src: Path, agent: str, model: str, dest: Path) -> Path:
    """Lay out a minimal opencode project under ``dest``: the tool at
    ``.opencode/tools/<name>.ts`` plus an ``opencode.json`` defining ``agent``.
    ``model`` is only for agent-config resolution — the probe never calls it."""
    tools_dir = dest / ".opencode" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(tool_src, tools_dir / tool_src.name)
    config = {
        "$schema": "https://opencode.ai/config.json",
        "agent": {agent: {"prompt": "tool-validation probe", "model": model}},
    }
    (dest / "opencode.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    return dest


def _probe_command(sandbox, workdir: str, agent: str) -> list[str]:
    """Argv to run ``opencode debug agent`` against the probe workdir.

    ``opencode debug agent`` reads the project from the CWD (there is no ``--dir``
    flag), so the caller runs it with ``cwd=workdir`` in host mode; in container
    mode ``-w`` sets the in-container cwd to the mounted workdir. Container mode
    mounts ONLY the probe workdir — no provider ``-e`` env and no cache mounts,
    because registration neither calls a model nor executes the tool body."""
    inner = ["opencode", "debug", "agent", agent,
             "--print-logs", "--log-level", "DEBUG"]
    if sandbox.mode != "container":
        return inner
    return [sandbox.runtime, "run", "--rm",
            "-v", f"{workdir}:{sandbox.workdir_mount}",
            "-w", sandbox.workdir_mount,
            sandbox.image, *inner]


def validate_tool(tool_src, *, sandbox, agent: str = "abench",
                  model: str = "deepseek/deepseek-chat") -> ToolValidation:
    """Validate one OpenCode custom tool in ``sandbox``. Returns a ToolValidation.

    Builds a throwaway opencode project containing only this tool, runs
    ``opencode debug agent`` against it (in the container for mode='container'),
    and reports whether the tool is registered + any load errors. The ``model``
    is only for agent-config resolution; ``debug agent`` never calls it.
    """
    tool_src = Path(tool_src)
    tool_name = tool_src.stem
    with tempfile.TemporaryDirectory(prefix="abench-toolval-") as tmp:
        workdir = _build_probe_workdir(tool_src, agent, model, Path(tmp))
        cmd = _probe_command(sandbox, str(workdir), agent)
        # host mode: opencode reads the project from cwd; container mode: the
        # in-container cwd is set by `-w`, so the host docker process needs none.
        cwd = None if sandbox.mode == "container" else str(workdir)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=120, cwd=cwd)
        except subprocess.TimeoutExpired:
            return ToolValidation(tool_name, False,
                                  ["opencode debug agent timed out after 120s"], -1, "")
        except FileNotFoundError as exc:
            return ToolValidation(tool_name, False,
                                  [f"could not run probe: {exc}"], -1, "")
        return _parse_probe(tool_name, proc.returncode, proc.stdout, proc.stderr)
