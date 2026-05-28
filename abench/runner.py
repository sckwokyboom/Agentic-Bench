# abench/runner.py
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Callable

import yaml

from . import fixture as fx
from .config import Condition, Experiment
from .metrics import MetricsConfig, extract
from .opencode_client import OpenCodeClient
from .prompt import compose

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

    total = len(exp.conditions) * exp.repetitions
    t_exp = time.time()
    _log(
        f"[abench] experiment={exp.name} model={exp.model} "
        f"total_runs={total} timeout_s={exp.timeout_s} output_dir={root}"
    )

    idx = 0
    for cond in exp.conditions:
        for rep in range(exp.repetitions):
            idx += 1
            _log(
                f"[abench] ───── run {idx}/{total}: "
                f"condition={cond.name} rep={rep} ─────"
            )
            t_run = time.time()
            _run_one(exp, cond, rep, root, client, mcfg)
            _log(
                f"[abench] run {idx}/{total} done in {time.time() - t_run:.1f}s"
            )
            if exp.min_seconds_between_runs:
                _log(f"[abench] cooldown {exp.min_seconds_between_runs}s")
                time.sleep(exp.min_seconds_between_runs)
    _log(
        f"[abench] experiment finished in {time.time() - t_exp:.1f}s → {root}"
    )
    return root


def _run_one(exp: Experiment, cond: Condition, rep: int, root: Path,
             client: OpenCodeClient, mcfg: MetricsConfig) -> None:
    rundir = root / cond.name / f"rep_{rep}"
    rundir.mkdir(parents=True, exist_ok=True)

    workdir, sha = fx.create_workdir(exp.fixture_path)
    try:
        user_message = compose(exp.task_prompt, cond.augmentation)

        events_file = (rundir / "events.jsonl").open("w")

        def on_event(event: dict) -> None:
            events_file.write(json.dumps(event) + "\n")
            events_file.flush()

        try:
            result = client.run_task(
                workdir=str(workdir),
                system_prompt=exp.system_prompt,
                model=exp.model,
                user_message=user_message,
                timeout_s=exp.timeout_s,
                on_event=on_event,
            )
        finally:
            events_file.close()

        (rundir / "trace.json").write_text(json.dumps(result.trace.to_dict(), indent=2))
        patch = fx.diff_workdir(workdir)
        (rundir / "changes.patch").write_text(patch)

        metrics = extract(result.trace, patch, mcfg)
        (rundir / "metrics.json").write_text(json.dumps(metrics, indent=2))

        tr = result.trace
        _log(
            f"[abench] result: finished={tr.finished} "
            f"reason={tr.interrupted_reason} steps={len(tr.steps)} "
            f"tokens_in={tr.tokens_in} tokens_out={tr.tokens_out}"
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
