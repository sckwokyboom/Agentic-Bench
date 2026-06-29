"""Re-verify an existing run's saved result without re-running the agent."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Iterator

from . import fixture as fx
from .config import Experiment
from .metrics import _success_from_status
from .run_layout import batch_runs_dir
from .verify import (
    VerifyResult, augment_for_authoritative_run, detect_command, run_verify,
    undercount_override, write_verify_log,
)


def _runs_root(exp: Experiment, batch: str | None) -> Path | None:
    """Resolve the runs dir for the chosen batch under <exp>/runs/<exp>.

    batch=None → newest batch (or the flat/legacy layout if that's all there
    is). Returns None if no runs resolve."""
    return batch_runs_dir(exp.output_dir / exp.name, batch)


def _rundir(exp: Experiment, condition: str, rep: int, batch: str | None = None) -> Path | None:
    runs_root = _runs_root(exp, batch)
    if runs_root is None:
        return None
    return runs_root / condition / f"rep_{rep}"


def discover_runs(exp: Experiment, batch: str | None = None) -> list[tuple[str, int]]:
    root = _runs_root(exp, batch)
    out: list[tuple[str, int]] = []
    if root is None or not root.is_dir():
        return out
    for cond_dir in sorted(root.iterdir()):
        if not cond_dir.is_dir():
            continue
        for rep_dir in sorted(cond_dir.iterdir()):
            if (rep_dir.is_dir() and rep_dir.name.startswith("rep_")
                    and (rep_dir / "changes.patch").is_file()):
                out.append((cond_dir.name, int(rep_dir.name.removeprefix("rep_"))))
    return out


def _baseline_expected_total(exp: Experiment) -> int | None:
    """Full expected suite size = the reference's passing count from the baseline
    cache (trustworthy only when the reference itself verified green)."""
    cache = exp.fixture_path.parent / ".verify-baseline.json"
    if not cache.is_file():
        return None
    try:
        b = json.loads(cache.read_text())
    except (OSError, ValueError):
        return None
    if b.get("status") == "passed" and b.get("passed_count"):
        return int(b["passed_count"])
    return None


def _backup_once(rundir: Path) -> None:
    """Snapshot the pre-re-verify artifacts to ``<name>.orig`` so the original
    recorded result is always restorable. Written ONCE per run — a later
    re-verify keeps the first (true original) backup, never overwrites it.

    Re-verify only ever rewrites the verify_* verdict fields (never the agent
    trace: steps/turns/tokens/the patch/events.jsonl are untouched), but we
    snapshot anyway so a reconstruction that goes wrong — a patch that no longer
    applies, or environment drift — can never cost you a recorded result."""
    for name in ("trace.json", "metrics.json", "verify_output.log"):
        src = rundir / name
        bak = rundir / f"{name}.orig"
        if src.is_file() and not bak.exists():
            shutil.copy2(src, bak)


def _write_back(rundir: Path, v: VerifyResult, expected_total: int | None = None) -> None:
    _backup_once(rundir)
    verify_fields = {
        "verify_status": v.status,
        "verify_command": v.command,
        "verify_duration_s": v.duration_s,
        "verify_passed_count": v.passed_count,
        "verify_failed_count": v.failed_count,
        "verify_failed_names": list(v.failed_names),
        "verify_reason": v.reason,
        "verify_message": v.message,
    }
    if expected_total is not None:
        verify_fields["verify_expected_total"] = expected_total
    tpath = rundir / "trace.json"
    if tpath.is_file():
        tr = json.loads(tpath.read_text())
        tr.update(verify_fields)
        tpath.write_text(json.dumps(tr, indent=2))
    mpath = rundir / "metrics.json"
    if mpath.is_file():
        m = json.loads(mpath.read_text())
        m.update(verify_fields)
        m["success"] = _success_from_status(v.status)
        mpath.write_text(json.dumps(m, indent=2))
    write_verify_log(rundir, v)


def reverify_run(
    exp: Experiment, condition: str, rep: int, batch: str | None = None
) -> VerifyResult:
    rundir = _rundir(exp, condition, rep, batch)
    if rundir is None or not rundir.is_dir() or not (rundir / "changes.patch").is_file():
        return VerifyResult(
            status="error", reason="no_run",
            message=f"no saved run at {condition}/rep_{rep}",
        )
    expected = _baseline_expected_total(exp)
    patch = rundir / "changes.patch"
    workdir, _sha = fx.create_workdir(exp.fixture_path)
    try:
        applied = subprocess.run(
            ["git", "apply", str(patch)], cwd=workdir,
            capture_output=True, text=True,
        )
        if applied.returncode != 0:
            v = VerifyResult(
                status="error", reason="patch_apply_failed",
                message="could not reconstruct workdir: changes.patch did not apply "
                        "(fixture changed?)",
                raw_output=applied.stderr,
            )
            _write_back(rundir, v, expected)
            return v
        # Authoritative grading run (same as the live runner): force a FULL
        # re-execution so the suite isn't undercounted by gradle up-to-date skips.
        command = augment_for_authoritative_run(exp.verify.command or detect_command(workdir))
        if command is None:
            v = VerifyResult(status="skipped", reason="skipped",
                             message="no build system detected")
            _write_back(rundir, v, expected)
            return v
        v = run_verify(workdir, command, exp.verify.timeout_s)
        _ov = undercount_override(v.status, v.passed_count, v.failed_count, expected)
        if _ov is not None:
            v.status, v.reason, v.message = _ov
        _write_back(rundir, v, expected)
        return v
    finally:
        fx.cleanup(workdir)


def reverify_experiment(
    exp: Experiment, batch: str | None = None
) -> Iterator[tuple[str, int, VerifyResult]]:
    for condition, rep in discover_runs(exp, batch):
        yield condition, rep, reverify_run(exp, condition, rep, batch)
