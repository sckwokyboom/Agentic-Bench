# abench/diffstat.py
from __future__ import annotations


def parse_diffstat(patch: str) -> tuple[int, int, int]:
    """Return (n_files, lines_added, lines_removed) from a unified git diff."""
    files = 0
    added = 0
    removed = 0
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            files += 1
        elif line.startswith("+++ ") or line.startswith("--- "):
            continue
        elif line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return files, added, removed
