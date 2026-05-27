# abench/runner.py
from __future__ import annotations

import json
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

    for cond in exp.conditions:
        for rep in range(exp.repetitions):
            _run_one(exp, cond, rep, root, client, mcfg)
            if exp.min_seconds_between_runs:
                time.sleep(exp.min_seconds_between_runs)
    return root


def _run_one(exp: Experiment, cond: Condition, rep: int, root: Path,
             client: OpenCodeClient, mcfg: MetricsConfig) -> None:
    rundir = root / cond.name / f"rep_{rep}"
    rundir.mkdir(parents=True, exist_ok=True)

    workdir, sha = fx.create_workdir(exp.fixture_path)
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
    (rundir / "manifest.json").write_text(json.dumps({
        "condition": cond.name,
        "rep": rep,
        "model": exp.model,
        "fixture_sha": sha,
        "user_message": user_message,
    }, indent=2))

    fx.cleanup(workdir)
