"""Run the model-reachability probe in the experiment's sandbox and parse it.
The api key is supplied via the subprocess env (name-only ``-e``), never argv."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import credentials

_PROBE = str(Path(__file__).resolve().parent / "model_probe.py")


@dataclass
class ReachabilityResult:
    reachable: bool
    reason: str
    detail: str = ""


def _probe_command(sandbox, provider, model: str, probe_path: str) -> list[str]:
    key_env = provider.api_key_env or "OPENAI_API_KEY"
    inner_args = [provider.base_url, model, key_env]
    if sandbox.mode != "container":
        return ["python3", probe_path, *inner_args]
    return [sandbox.runtime, "run", "--rm",
            "-e", key_env,
            "-v", f"{probe_path}:/probe.py:ro",
            sandbox.image, "python3", "/probe.py",
            provider.base_url, model, key_env]


def validate_reachability(provider, model: str, *, sandbox) -> ReachabilityResult:
    """Probe ``model`` at ``provider.base_url`` with the provider's key, inside
    the sandbox. Returns a key-free ReachabilityResult."""
    cmd = _probe_command(sandbox, provider, model, _PROBE)
    env = credentials.run_env([provider])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
    except subprocess.TimeoutExpired:
        return ReachabilityResult(False, "probe_failed", "probe timed out")
    except FileNotFoundError as exc:
        return ReachabilityResult(False, "probe_failed", f"could not run probe: {exc}")
    try:
        data = json.loads(proc.stdout)
        return ReachabilityResult(bool(data["reachable"]), str(data["reason"]),
                                  str(data.get("detail", "")))
    except (json.JSONDecodeError, KeyError, TypeError):
        tail = (proc.stderr or proc.stdout or "").strip()[-200:]
        return ReachabilityResult(False, "probe_failed", tail)
