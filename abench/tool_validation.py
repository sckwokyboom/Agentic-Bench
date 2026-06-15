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
