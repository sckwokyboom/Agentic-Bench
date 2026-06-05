"""Recompute per-run metrics from stored artifacts — no agent re-run.

Re-derives the extract()-level metrics for runs already on disk (e.g.
tests_executed with the current parser, token totals via the per-turn fallback),
so a metric/parser change doesn't require re-running the experiment. The verify
verdict and every run-level field are preserved (loaded from the existing
trace.json). Token totals are filled from the per-turn step-finish data already
stored in the trace, so nothing extra is needed beyond trace.json + changes.patch.
"""
from __future__ import annotations

import json
from pathlib import Path

from .metrics import MetricsConfig, extract
from .trace_model import trace_from_dict
from .trace_normalize import fill_missing_token_totals


def recompute_run(rundir: Path, mcfg: MetricsConfig) -> dict | None:
    """Recompute metrics.json (and refresh trace.json's token totals) for one
    run dir from its trace.json + changes.patch. Returns the new metrics dict,
    or None if there's no usable trace to recompute from."""
    rundir = Path(rundir)
    trace_path = rundir / "trace.json"
    if not trace_path.is_file():
        return None
    try:
        trace = trace_from_dict(json.loads(trace_path.read_text()))
    except (OSError, ValueError, TypeError):
        return None
    fill_missing_token_totals(trace)
    patch_path = rundir / "changes.patch"
    patch = patch_path.read_text() if patch_path.is_file() else ""
    metrics = extract(trace, patch, mcfg)
    trace_path.write_text(json.dumps(trace.to_dict(), indent=2))
    (rundir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    return metrics


def recompute_batch(runs_dir: Path, mcfg: MetricsConfig) -> int:
    """Recompute every rep dir (``<condition>/rep_N``) under runs_dir. Returns
    the number of runs recomputed."""
    runs_dir = Path(runs_dir)
    n = 0
    for trace_path in sorted(runs_dir.glob("*/rep_*/trace.json")):
        if recompute_run(trace_path.parent, mcfg) is not None:
            n += 1
    return n
