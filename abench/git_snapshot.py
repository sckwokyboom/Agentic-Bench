"""Robust full-worktree snapshot/restore + edit allowlist for the orchestrator.

snapshot() records a tree object (tracked + currently-untracked, honoring
.gitignore so build/ is excluded); restore() rewinds the worktree to it,
including reverting modifications, deletions, and removing files created since.
Uses plumbing that never moves HEAD or the branch ref.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout


def snapshot(repo: Path) -> str:
    """Stage everything (respecting .gitignore) and return a tree SHA capturing
    the current worktree. Does not commit or move any ref."""
    _git(repo, "add", "-A")
    return _git(repo, "write-tree").strip()


def restore(repo: Path, tree: str) -> None:
    """Rewind the worktree to the snapshot tree: load it into the index, write
    every entry out (overwriting/restoring), then drop non-ignored files that
    are not in the snapshot. build/ etc. (gitignored) are left untouched."""
    _git(repo, "read-tree", tree)
    _git(repo, "checkout-index", "-a", "-f")
    _git(repo, "clean", "-fd")


def forbidden_changes(repo: Path, allowed_prefixes: list[str]) -> list[str]:
    """Changed paths (tracked or untracked) that fall OUTSIDE the allowlist —
    e.g. edits to src/test, build.gradle, configs. The orchestrator reverts
    these. Rename lines ('R old -> new') report the destination path."""
    out = _git(repo, "status", "--porcelain")
    changed: list[str] = []
    for ln in out.splitlines():
        if not ln.strip():
            continue
        path = ln[3:].strip()
        if " -> " in path:                      # rename: check the destination
            path = path.split(" -> ", 1)[1]
        changed.append(path)
    return [p for p in changed if not any(p.startswith(a) for a in allowed_prefixes)]
