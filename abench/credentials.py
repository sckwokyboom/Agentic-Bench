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


# Bearer token used when a provider has NO key anywhere — for a no-auth personal/
# local endpoint, which ignores it. opencode's openai-compatible provider needs
# SOME apiKey or it errors "Failed to get the authorization header", so this
# placeholder keeps a keyless endpoint working. A real auth endpoint rejects it
# (401) — provide a real key for those. Not a secret.
NO_KEY_PLACEHOLDER = "no-key-required"


def run_env(providers, session_keys=None, *, isolated=False) -> dict[str, str]:
    """``os.environ`` overlaid with the API key for each provider whose
    ``api_key_env`` is set.

    Default (single-user): OS env wins, then ``auth.json``, then
    ``NO_KEY_PLACEHOLDER`` — unchanged behaviour.

    ``isolated=True`` (the exposed LAN UI): use ONLY ``session_keys`` — the current
    visitor's per-session key. Any operator env var is OVERWRITTEN so it never leaks
    into a visitor's run, and the shared ``auth.json`` is NOT consulted. A provider
    with no session key gets ``NO_KEY_PLACEHOLDER``.

    The value is placed in the env dict, never in argv, never logged."""
    env = os.environ.copy()
    session_keys = session_keys or {}
    for prov in providers:
        name = getattr(prov, "api_key_env", None)
        if not name:
            continue
        if isolated:
            env[name] = session_keys.get(prov.id) or NO_KEY_PLACEHOLDER
        elif not env.get(name):
            env[name] = read_credential(prov.id) or NO_KEY_PLACEHOLDER
    return env
