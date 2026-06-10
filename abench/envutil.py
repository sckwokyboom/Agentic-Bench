"""'{env:NAME}' indirection shared by sandbox cache_mounts and overlay_env."""
from __future__ import annotations

import os
import re

_ENV_REF = re.compile(r"\{env:([A-Za-z_][A-Za-z0-9_]*)\}")


def expand_env_refs(value: str) -> str:
    def sub(m: re.Match) -> str:
        name = m.group(1)
        if name not in os.environ:
            raise ValueError(
                f"environment variable {name} referenced as {{env:{name}}} is not set")
        return os.environ[name]
    return _ENV_REF.sub(sub, value)
