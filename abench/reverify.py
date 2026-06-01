"""Re-verify an existing run's saved result without re-running the agent."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Iterator

from . import fixture as fx
from .config import Experiment
from .metrics import _success_from_status
from .verify import VerifyResult, detect_command, run_verify, write_verify_log


def _rundir(exp: Experiment, condition: str, rep: int) -> Path:
    return exp.output_dir / exp.name / condition / f"rep_{rep}"


def discover_runs(exp: Experiment) -> list[tuple[str, int]]:
    root = exp.output_dir / exp.name
    out: list[tuple[str, int]] = []
    if not root.is_dir():
        return out
    for cond_dir in sorted(root.iterdir()):
        if not cond_dir.is_dir():
            continue
        for rep_dir in sorted(cond_dir.iterdir()):
            if (rep_dir.is_dir() and rep_dir.name.startswith("rep_")
                    and (rep_dir / "changes.patch").is_file()):
                out.append((cond_dir.name, int(rep_dir.name.removeprefix("rep_"))))
    return out


def _write_back(rundir: Path, v: VerifyResult) -> None:
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


def reverify_run(exp: Experiment, condition: str, rep: int) -> VerifyResult:
    rundir = _rundir(exp, condition, rep)
    patch = rundir / "changes.patch"
    if not rundir.is_dir() or not patch.is_file():
        return VerifyResult(
            status="error", reason="no_run",
            message=f"no saved run at {condition}/rep_{rep}",
        )
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
            _write_back(rundir, v)
            return v
        command = exp.verify.command or detect_command(workdir)
        if command is None:
            v = VerifyResult(status="skipped", reason="skipped",
                             message="no build system detected")
            _write_back(rundir, v)
            return v
        v = run_verify(workdir, command, exp.verify.timeout_s)
        _write_back(rundir, v)
        return v
    finally:
        fx.cleanup(workdir)


def reverify_experiment(exp: Experiment) -> Iterator[tuple[str, int, VerifyResult]]:
    for condition, rep in discover_runs(exp):
        yield condition, rep, reverify_run(exp, condition, rep)
