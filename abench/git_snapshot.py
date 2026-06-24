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
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if proc.returncode != 0:
        # Surface git's stderr in the message — a bare CalledProcessError hides
        # WHY it failed (permission denied, locked file, nested repo, …), which
        # made these failures undiagnosable in the run log.
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"git {' '.join(args)} failed (exit {proc.returncode}): {detail[:2000]}")
    return proc.stdout


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
    # Drop untracked files the round added. -ffd (double force) also removes
    # untracked NESTED git repos (e.g. opencode/tool state) that plain -fd REFUSES
    # — that refusal crashed the diagnose loop with a bare exit 1. Best-effort:
    # the tracked source is already reverted above, so a residual file git still
    # can't remove (root-owned from the container, or a locked Windows/WSL handle)
    # must NOT abort the run — git removes everything removable first and only then
    # reports the leftover, so tolerating it is safe (gitignored build/ is skipped;
    # leftover cruft is harmless and gradle rebuilds).
    try:
        _git(repo, "clean", "-ffd")
    except Exception:
        pass


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
