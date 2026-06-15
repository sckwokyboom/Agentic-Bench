"""Read the opencode auth.json secret store and assemble run/probe subprocess
env. The API key is handled ONLY here + forwarded by env NAME — never logged,
never placed in argv, never returned to callers/UI.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def auth_path() -> Path:
    """opencode's auth store, XDG-aware (matches opencode's own resolution)."""
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "opencode" / "auth.json"


def read_credential(provider: str) -> str | None:
    """The api key for ``provider`` from auth.json, or None. Secret — never log."""
    p = auth_path()
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    entry = data.get(provider) if isinstance(data, dict) else None
    if isinstance(entry, dict):
        key = entry.get("key")
        return key if isinstance(key, str) and key else None
    return None


def has_credential(provider: str) -> bool:
    return read_credential(provider) is not None


def run_env(providers) -> dict[str, str]:
    """``os.environ`` overlaid with auth.json keys for each provider whose
    ``api_key_env`` is not already set in the environment (OS env wins; auth.json
    is the fallback). The value is placed in the env dict, never in argv."""
    env = os.environ.copy()
    for prov in providers:
        name = getattr(prov, "api_key_env", None)
        if name and not env.get(name):
            key = read_credential(prov.id)
            if key:
                env[name] = key
    return env
