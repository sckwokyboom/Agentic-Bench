"""Timestamped-batch run layout helpers.

Runs are stored at ``<exp>/runs/<exp>/<batch_id>/<cond>/rep_N/``. A legacy FLAT
layout (``<exp>/runs/<exp>/<cond>/rep_N/`` directly under the root) is surfaced
as the synthetic batch id ``"legacy"`` (no files moved).

These live in core ``abench/`` (not ``abench_ui``) so that core modules such as
``abench.reverify`` can resolve a batch dir without importing the UI package.
``abench_ui.runs`` re-exports them for the server + existing tests. They operate
on a plain ``Path`` — the ``<exp>/runs/<exp>`` root.
"""
from __future__ import annotations

import json
from pathlib import Path


def _has_run_dirs(runs_dir: Path) -> bool:
    """A runs dir is laid out as <runs_dir>/<cond>/rep_*/... — true if any such
    rep directory exists. Structural (doesn't require metrics.json) so artefact
    endpoints resolve even for runs that only wrote e.g. a verify log."""
    for cond_dir in runs_dir.iterdir() if runs_dir.is_dir() else []:
        if not cond_dir.is_dir():
            continue
        for rep_dir in cond_dir.iterdir():
            if rep_dir.is_dir() and rep_dir.name.startswith("rep_"):
                return True
    return False


def _count_runs(runs_dir: Path) -> tuple[int, int]:
    """Return (total_runs, valid_runs) for a runs dir laid out as
    <runs_dir>/<cond>/rep_*/metrics.json. valid_runs = runs whose metrics
    carry success not None."""
    total = 0
    valid = 0
    for m_path in runs_dir.glob("*/rep_*/metrics.json"):
        if not m_path.is_file():
            continue
        total += 1
        try:
            m = json.loads(m_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if m.get("success") is not None:
            valid += 1
    return total, valid


def list_batches(exp_runs_root: Path) -> list[dict]:
    """Newest-first batches under <exp>/runs/<exp>/. A batch dir contains
    <cond>/rep_*/ run directories. If no batch dirs exist but a legacy FLAT
    layout does (<cond>/rep_*/ directly under the root), surface it as a single
    synthetic batch id 'legacy' (no files moved).

    Returns one dict per batch: {"id", "total_runs", "valid_runs"} (counts are
    metrics-based: total_runs = rep dirs with metrics.json, valid_runs = those
    whose metrics carry success not None).

    Sorted by id descending (timestamp ids sort chronologically); "legacy"
    sorts last.
    """
    root = Path(exp_runs_root)
    if not root.is_dir():
        return []

    batches: list[dict] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        # A batch dir D has grandchildren D/<cond>/rep_*/ run directories.
        if _has_run_dirs(child):
            total, valid = _count_runs(child)
            batches.append({"id": child.name, "total_runs": total, "valid_runs": valid})

    if batches:
        # Newest-first by id; only real batch dirs reach here, so a plain
        # descending sort gives chronological-newest-first for timestamp ids.
        batches.sort(key=lambda b: b["id"], reverse=True)
        return batches

    # No batch dirs — check for a legacy flat layout directly under root.
    if _has_run_dirs(root):
        total, valid = _count_runs(root)
        return [{"id": "legacy", "total_runs": total, "valid_runs": valid}]

    return []


def batch_runs_dir(exp_runs_root: Path, batch: str | None) -> Path | None:
    """Resolve the runs dir for a batch.

    None/'' -> newest batch (or flat root if legacy).
    'legacy' -> the flat root.
    Otherwise <root>/<batch>.

    Returns None if the resolved dir doesn't exist / has no runs.
    """
    root = Path(exp_runs_root)
    batches = list_batches(root)
    if not batches:
        return None

    if not batch:
        # Newest by default — list_batches already sorted newest-first.
        top = batches[0]["id"]
        return root if top == "legacy" else root / top

    if batch == "legacy":
        # Only valid if the root actually has a flat layout.
        if any(b["id"] == "legacy" for b in batches):
            return root
        return None

    # Path-traversal guard: a batch id must resolve to a direct child of root.
    target = (root / batch).resolve()
    try:
        if target.parent != root.resolve():
            return None
    except OSError:
        return None
    if any(b["id"] == batch for b in batches):
        return root / batch
    return None
