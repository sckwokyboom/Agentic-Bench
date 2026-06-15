"""Provider list + auth.json writer."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from abench.credentials import auth_path


def list_providers() -> list[dict]:
    path = auth_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return []
    return [{"id": pid, "configured": True} for pid in sorted(data)]


def write_credentials(provider: str, api_key: str) -> None:
    path = auth_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text())
        except json.JSONDecodeError:
            existing = {}
    existing[provider] = {"type": "api", "key": api_key}
    _atomic_write(path, json.dumps(existing, indent=2))


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
