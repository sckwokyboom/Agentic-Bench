"""Benchmark run loop. Reuses the existing run primitives; materializes each
instance via its adapter and grades via adapter.grade (dual-grading). Kept
separate from the fixture-mode _run_one so the working fixture path is untouched.

DEFERRED (later plans): retry / rate-limit / idle-timeout parity, isolation
ground-rules + nonce in the system prompt, per-condition tool gating."""
from __future__ import annotations

import dataclasses
import json
import re
import tempfile
import traceback
from pathlib import Path
from typing import Any, Callable

from ..fixture import _git_init_commit, cleanup, diff_workdir
from ..metrics import extract
from ..prompt import compose
from . import registry
from .expand import expand_plan


def _safe_instance_dirname(instance_id: str) -> str:
    """Filesystem-safe directory name for an instance id (e.g. 'PA19/Cell.java')."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", instance_id)


def _verify_status_for(resolved: bool | None) -> str:
    if resolved is True:
        return "passed"
    if resolved is False:
        return "failed"
    return "skipped"


def run_benchmark(exp, client, mcfg, overlay_env: dict[str, str], root: Path,
                  *, emit: "Callable[[dict], None] | None" = None,
                  cancel_event: Any = None,
                  context_window: "int | None" = None) -> None:
    emit = emit or (lambda _p: None)
    adapter = registry.get_adapter(exp.benchmark.adapter)
    instances = list(adapter.load(exp.benchmark.dataset, exp.benchmark.subset or None))
    plan = expand_plan(exp, instances)

    for run in plan:
        if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
            break
        inst, cond, rep = run.instance, run.condition, run.rep
        rundir = root / _safe_instance_dirname(inst.instance_id) / cond.name / f"rep_{rep}"
        rundir.mkdir(parents=True, exist_ok=True)

        # Per-run safety net: an exception from any step below (materialize,
        # git init, the agent, diff, grade, ...) is recorded to error.log and the
        # sweep continues — one bad instance must not kill a 91-instance run.
        # Mirrors the fixture path (runner._run_one records a crash + continues).
        workdir = None
        try:
            workdir = Path(tempfile.mkdtemp(prefix="abench-bench-"))
            adapter.materialize(inst.agent_view(), workdir)
            _git_init_commit(workdir, message="materialized")

            events_file = (rundir / "events.jsonl").open("w")

            def on_event(event: dict) -> None:
                events_file.write(json.dumps(event) + "\n")
                events_file.flush()

            user_message = compose(inst.task.prompt_text, cond.augmentation)
            try:
                result = client.run_task(
                    workdir=str(workdir),
                    system_prompt=exp.system_prompt,
                    model=exp.model,
                    user_message=user_message,
                    timeout_s=exp.timeout_s,
                    agent_tools=None,
                    on_event=on_event,
                    temperature=cond.temperature,
                )
            finally:
                events_file.close()

            patch = diff_workdir(workdir)
            (rundir / "changes.patch").write_text(patch)

            grade = adapter.grade(inst, patch, workdir)
            result.trace.verify_status = _verify_status_for(grade.resolved)

            (rundir / "trace.json").write_text(json.dumps(result.trace.to_dict(), indent=2))
            (rundir / "grade.json").write_text(json.dumps(dataclasses.asdict(grade), indent=2))

            metrics = extract(result.trace, patch, mcfg)
            metrics["benchmark"] = {
                "instance_id": inst.instance_id,
                "repo": inst.repo,
                "adapter": adapter.id,
                "standard_protocol": grade.standard_protocol,
                "official": {"resolved": grade.resolved, "evaluator": grade.evaluator},
                "abench": grade.abench,
            }
            (rundir / "metrics.json").write_text(json.dumps(metrics, indent=2))
            emit({"phase": "bench_run", "instance": inst.instance_id,
                  "condition": cond.name, "rep": rep, "resolved": grade.resolved})
        except Exception as exc:
            (rundir / "error.log").write_text("".join(traceback.format_exception(exc)))
            emit({"phase": "bench_run_error", "instance": inst.instance_id,
                  "condition": cond.name, "rep": rep, "error": repr(exc)})
        finally:
            if workdir is not None:
                cleanup(workdir)
