# abench/libraries.py
"""Machine-local library registry (.abench.local.json) + {lib:NAME} resolution.

The registry maps a logical library name to its HOST path (e.g. where
Graph-Tipper is checked out). It is gitignored and machine-specific — the
UI/CLI edit it, the runner reads it — so experiment YAML stays portable and no
OS env var is needed to point at a local tool.
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
