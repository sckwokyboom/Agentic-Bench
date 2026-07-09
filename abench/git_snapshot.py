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


def restore_except(repo: Path, keep: list[str]) -> None:
    """Revert the worktree to the seed commit (HEAD) for EVERY tracked path
    except those in ``keep`` (the graded target file), and drop untracked files
    the agent created (scratch tests, debug `main`s). gitignored build output is
    left intact so verify need not recompile from scratch.

    Used by the forced-instrument condition to strip temporary test
    instrumentation before grading: the agent is allowed to add debug prints to
    tests while it works, but the verdict must reflect ONLY its edits to the
    target file. A no-op when the agent changed nothing outside ``keep``.
    """
    # ':(exclude)<path>' magic pathspec keeps the target's edits while every
    # other tracked file is reset to HEAD.
    excludes = [f":(exclude){p}" for p in keep]
    _git(repo, "checkout", "HEAD", "--", ".", *excludes)
    # Remove untracked files the round added (new scratch test files, debug
    # harnesses). Plain -fd keeps gitignored build/ (no -x), so the warmed
    # Gradle output survives. Best-effort: a residual root-owned/locked file
    # must not abort the run.
    try:
        _git(repo, "clean", "-fd")
    except Exception:
        pass


def strip_marked_lines(repo: Path, rel_path: str, marker: str = "//[probe]") -> int:
    """Delete every line containing ``marker`` from repo/rel_path; return the
    count removed.

    The forced-instrument condition encourages the agent to add temporary debug
    prints — and to mark each with a trailing ``//[probe]`` comment — INTO the
    code too, not just tests. Test-file probes are reverted wholesale by
    restore_except, but the graded target file keeps the agent's edits, so a
    forgotten probe there would survive into verify (corrupting stdout-capturing
    tests → a spurious fail) and into the artifact. This strips the marked debug
    lines from the target before grading, leaving the real implementation (which
    carries no marker) untouched. Best-effort: a missing/binary file is a no-op.
    """
    p = repo / rel_path
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 0
    lines = text.splitlines(keepends=True)
    kept = [ln for ln in lines if marker not in ln]
    removed = len(lines) - len(kept)
    if removed:
        p.write_text("".join(kept), encoding="utf-8")
    return removed


def strip_probe_lines_repo(repo: Path, marker: str = "//[probe]") -> int:
    """Strip marked probe lines from EVERY changed .java file (tracked or
    untracked) — the rcc loop's mid-run cleanup after the instrumented subset
    run. Per-file work is strip_marked_lines. Returns total lines removed;
    best-effort (a git failure returns 0 rather than aborting the run)."""
    try:
        out = _git(repo, "status", "--porcelain")
    except Exception:
        return 0
    total = 0
    for ln in out.splitlines():
        if not ln.strip():
            continue
        path = ln[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path.endswith(".java"):
            total += strip_marked_lines(repo, path, marker=marker)
    return total


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
