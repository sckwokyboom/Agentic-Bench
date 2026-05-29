# abench/runner.py
from __future__ import annotations

import datetime
import hashlib
import json
import random
import sys
import time
import uuid
from pathlib import Path
from typing import Callable

import yaml

from . import fixture as fx
from .config import Condition, Experiment
from .diffstat import parse_diffstat
from .metrics import MetricsConfig, extract
from .opencode_client import OpenCodeClient
from .prompt import compose
from .trace_model import FileChange, FinalDiffSummary
from .verify import detect_command as _detect_verify, run_verify

ClientFactory = Callable[[Experiment], OpenCodeClient]


def _log(msg: str) -> None:
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def _dump_resolved(exp: Experiment) -> str:
    def conv(obj):
        if isinstance(obj, Path):
            return str(obj)
        if isinstance(obj, dict):
            return {k: conv(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [conv(x) for x in obj]
        return obj
    return yaml.safe_dump(conv(exp.model_dump()), allow_unicode=True, sort_keys=False)


def run_experiment(exp: Experiment, client_factory: ClientFactory) -> Path:
    root = exp.output_dir / exp.name
    root.mkdir(parents=True, exist_ok=True)
    (root / "experiment.resolved.yaml").write_text(_dump_resolved(exp))

    mcfg = MetricsConfig(**exp.metrics.model_dump())
    client = client_factory(exp)

    plan: list[tuple[Condition, int]] = [
        (cond, rep) for cond in exp.conditions for rep in range(exp.repetitions)
    ]
    if exp.isolation.shuffle_order:
        raw = (exp.name + datetime.date.today().isoformat()).encode()
        seed = int(hashlib.sha256(raw).hexdigest()[:16], 16)
        random.Random(seed).shuffle(plan)

    # Baseline pre-flight verify
    if exp.verify.enabled:
        baseline_cache = exp.fixture_path.parent / ".verify-baseline.json"
        _maybe_run_baseline_verify(exp, baseline_cache)

    total = len(plan)
    t_exp = time.time()
    _log(
        f"[abench] experiment={exp.name} model={exp.model} "
        f"total_runs={total} timeout_s={exp.timeout_s} output_dir={root} "
        f"isolation: nonce={exp.isolation.nonce_prefix} shuffle={exp.isolation.shuffle_order}"
    )

    for idx, (cond, rep) in enumerate(plan, start=1):
        _log(
            f"[abench] ───── run {idx}/{total}: condition={cond.name} rep={rep} ─────"
        )
        t_run = time.time()
        _run_one(exp, cond, rep, root, client, mcfg)
        _log(f"[abench] run {idx}/{total} done in {time.time() - t_run:.1f}s")
        if exp.min_seconds_between_runs:
            _log(f"[abench] cooldown {exp.min_seconds_between_runs}s")
            time.sleep(exp.min_seconds_between_runs)
    _log(f"[abench] experiment finished in {time.time() - t_exp:.1f}s → {root}")
    return root


def _run_one(exp: Experiment, cond: Condition, rep: int, root: Path,
             client: OpenCodeClient, mcfg: MetricsConfig) -> None:
    rundir = root / cond.name / f"rep_{rep}"
    rundir.mkdir(parents=True, exist_ok=True)

    workdir, sha = fx.create_workdir(exp.fixture_path)
    try:
        # ── Isolation: nonce-prefix in system_prompt ──────────────────
        nonce: str | None = None
        system_prompt_eff = exp.system_prompt
        if exp.isolation.nonce_prefix:
            nonce = uuid.uuid4().hex
            system_prompt_eff = (
                f"# abench-run: {nonce}\n"
                f"# fixture: {sha}\n"
                f"{exp.system_prompt}"
            )

        user_message = compose(exp.task_prompt, cond.augmentation)

        events_file = (rundir / "events.jsonl").open("w")

        def on_event(event: dict) -> None:
            events_file.write(json.dumps(event) + "\n")
            events_file.flush()

        try:
            result = client.run_task(
                workdir=str(workdir),
                system_prompt=system_prompt_eff,
                model=exp.model,
                user_message=user_message,
                timeout_s=exp.timeout_s,
                on_event=on_event,
            )
        finally:
            events_file.close()

        # Record isolation nonce on the trace
        if nonce is not None:
            result.trace.isolation_nonce = nonce

        # ── Final diff + per-file summary ────────────────────────────
        patch = fx.diff_workdir(workdir)
        (rundir / "changes.patch").write_text(patch)
        _, added, removed = parse_diffstat(patch)
        per_file = _per_file_diffstat(patch)
        result.trace.final_diff_summary = FinalDiffSummary(
            files=[FileChange(path=p, added=a, removed=r) for (p, a, r) in per_file],
            total_added=added,
            total_removed=removed,
        )

        # ── Trace.json + metrics ─────────────────────────────────────
        (rundir / "trace.json").write_text(json.dumps(result.trace.to_dict(), indent=2))
        metrics = extract(result.trace, patch, mcfg)
        (rundir / "metrics.json").write_text(json.dumps(metrics, indent=2))

        # ── Verify (post-rep, before cleanup) ────────────────────────
        if exp.verify.enabled:
            verify_command = exp.verify.command or _detect_verify(workdir)
            if verify_command is None:
                result.trace.verify_status = "skipped"
            else:
                try:
                    v = run_verify(workdir, verify_command, exp.verify.timeout_s)
                    result.trace.verify_status = v.status
                    result.trace.verify_command = v.command
                    result.trace.verify_duration_s = v.duration_s
                    result.trace.verify_passed_count = v.passed_count
                    result.trace.verify_failed_count = v.failed_count
                    result.trace.verify_failed_names = v.failed_names
                except Exception as exc:
                    _log(f"[abench] WARN verify raised unexpectedly: {exc!r}")
                    result.trace.verify_status = "error"
                    result.trace.verify_command = verify_command

            # Check baseline cache and propagate unknown flag
            baseline_cache = exp.fixture_path.parent / ".verify-baseline.json"
            if baseline_cache.is_file():
                try:
                    baseline = json.loads(baseline_cache.read_text())
                    if baseline.get("status") != "passed":
                        result.trace.verify_baseline_unknown = True
                except Exception:
                    pass

            # Re-serialise trace.json with verify_* populated
            (rundir / "trace.json").write_text(json.dumps(result.trace.to_dict(), indent=2))
            # Refresh metrics (verify_* propagate via metrics.extract)
            metrics = extract(result.trace, patch, mcfg)
            (rundir / "metrics.json").write_text(json.dumps(metrics, indent=2))

        tr = result.trace
        _log(
            f"[abench] result: finished={tr.finished} "
            f"reason={tr.interrupted_reason} steps={len(tr.steps)} "
            f"tokens_in={tr.tokens_in} tokens_out={tr.tokens_out} "
            f"verify={tr.verify_status}"
        )
        if tr.verify_status not in (None, "passed", "skipped"):
            _log(
                f"[abench] WARN verify={tr.verify_status} "
                f"cmd={tr.verify_command} failed={tr.verify_failed_count}"
            )
        (rundir / "manifest.json").write_text(json.dumps({
            "condition": cond.name,
            "rep": rep,
            "model": exp.model,
            "fixture_sha": sha,
            "user_message": user_message,
        }, indent=2))
    finally:
        fx.cleanup(workdir)


def _per_file_diffstat(patch: str) -> list[tuple[str, int, int]]:
    """Return [(path, added, removed)] from a unified git diff."""
    files: list[tuple[str, int, int]] = []
    current: str | None = None
    added = 0
    removed = 0
    for line in patch.splitlines():
        if line.startswith("diff --git a/"):
            if current is not None:
                files.append((current, added, removed))
            # "diff --git a/<path> b/<path>"
            prefix = "diff --git a/"
            rest = line[len(prefix):]
            sep = rest.rfind(" b/")
            if sep != -1:
                current = rest[:sep]
            else:
                # Fallback for malformed headers
                parts = line.split()
                current = parts[2][2:] if len(parts) >= 4 else None
            added = removed = 0
        elif line.startswith("+++ ") or line.startswith("--- "):
            continue
        elif line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    if current is not None:
        files.append((current, added, removed))
    return files


def _maybe_run_baseline_verify(exp: Experiment, cache_path: Path) -> None:
    """Best-effort baseline verify; caches result in cache_path."""
    ref_sha = _dir_sha(exp.reference_path)
    if cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text())
            if cached.get("reference_sha") == ref_sha:
                return
        except Exception:
            pass
    # Run verify on a fresh copy of reference_path (best-effort; skip on any error)
    try:
        workdir, _sha = fx.create_workdir(exp.reference_path)
    except Exception:
        return
    try:
        command = exp.verify.command or _detect_verify(workdir)
        if command is None:
            return
        v = run_verify(workdir, command, exp.verify.timeout_s)
        cache_path.write_text(json.dumps({
            "command": command, "reference_sha": ref_sha,
            "status": v.status, "passed_count": v.passed_count,
            "failed_count": v.failed_count,
        }))
    except Exception:
        pass
    finally:
        fx.cleanup(workdir)


def _dir_sha(path: Path) -> str:
    """Cheap stable hash of a directory tree."""
    h = hashlib.sha1()
    for p in sorted(Path(path).rglob("*")):
        if p.is_file():
            h.update(p.relative_to(path).as_posix().encode())
            h.update(b"\x00")
            h.update(p.read_bytes())
    return h.hexdigest()[:16]
