"""JavaBench adapter (per-class, official class-wise Pass@1).

Instance = one skeleton class. materialize copies the PAxx skeleton project into
the workdir; the agent implements the target class. grade delegates to JavaBench's
own evaluate_single_class (replace the agent's class into the canonical solution,
compile, run all tests). Firewall: skeleton (projects/PAxx) is agent-visible;
canonical (projects/PAxx-Solution) is touched only inside grade().

The live grade needs a JavaBench checkout + Java/Gradle (prepared host); the pure
parts (load/materialize + grade wiring) are unit-tested with fixtures/mocks."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable

from . import registry
from .base import Anchors, AgentView, EnvSpec, GradeResult, Instance, TaskSpec

_DEFAULT_PROJECTS = ["PA19", "PA20", "PA21", "PA22"]
_DEFAULT_CONTEXT = "selective-context"
_EVALUATOR_PIN = "javabench-class-wise@java-bench/JavaBench"


def _run_javabench_grader(javabench_root: str, preds_file: str, out_file: str) -> list[dict]:
    """Run JavaBench's evaluate_single_class with cwd=javabench_root and return the
    parsed result list. Isolated so tests can monkeypatch it (the real call needs
    Java/Gradle + a JavaBench checkout). IMPLEMENTER: confirm the exact CLI/entry
    from evaluation.py; it MUST run with cwd=javabench_root (relative projects/ paths)."""
    subprocess.run(
        ["python", "-c",
         "import sys; sys.path.insert(0, '.'); from evaluation import evaluate_single_class; "
         f"evaluate_single_class({preds_file!r}, {out_file!r})"],
        cwd=javabench_root, check=True,
    )
    return json.loads(Path(out_file).read_text())


def _build_prompt(rec: dict) -> str:
    ctx = rec.get("code_context") or "(none)"
    return (
        f"Implement the Java class at `src/main/java/{rec['target']}` in this project. "
        "The file is present with stubbed method bodies marked `// TODO`; complete the "
        "implementation so the project's tests pass. Do not modify any test files.\n\n"
        "Related class signatures (context):\n" + ctx
    )


class JavaBenchAdapter:
    id = "javabench"

    def load(self, dataset: Path | None, subset: dict[str, Any] | None) -> Iterable[Instance]:
        if dataset is None:
            raise ValueError(
                "javabench adapter requires 'dataset' (path to a JavaBench checkout)"
            )
        root = Path(dataset)
        subset = subset or {}
        context = subset.get("context", _DEFAULT_CONTEXT)
        projects = [subset["project"]] if subset.get("project") else list(_DEFAULT_PROJECTS)
        for project_id in projects:
            data_file = root / "datasets" / context / f"data-{project_id}.jsonl"
            if not data_file.is_file():
                continue
            for line in data_file.read_text().splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                yield Instance(
                    instance_id=rec["task_id"],
                    repo=f"javabench/{project_id}",
                    task=TaskSpec(prompt_text=_build_prompt(rec)),
                    anchors=Anchors(),
                    env=EnvSpec(
                        image="none",
                        build_system="gradle",
                        source_dir=str(root / "projects" / project_id),
                    ),
                    oracle={
                        "javabench_root": str(root),
                        "project_id": project_id,
                        "target": rec["target"],
                    },
                )

    def materialize(self, view: AgentView, workdir: Path) -> None:
        src = Path(view.env.source_dir)
        shutil.copytree(src, workdir, dirs_exist_ok=True)
        gitdir = Path(workdir) / ".git"
        if gitdir.exists():
            shutil.rmtree(gitdir)

    def grade(self, inst: Instance, source_diff: str, workdir: Path) -> GradeResult:
        o = inst.oracle
        target = o["target"]
        agent_code = (Path(workdir) / "src" / "main" / "java" / target).read_text()
        completion = "```java\n" + agent_code + "\n```"
        tmp = Path(tempfile.mkdtemp(prefix="abench-jb-grade-"))
        try:
            preds = tmp / "preds.jsonl"
            out = tmp / "result.json"
            preds.write_text(json.dumps(
                {"task_id": inst.instance_id, "target": target, "completion": completion}) + "\n")
            results = _run_javabench_grader(o["javabench_root"], str(preds), str(out))
            r = results[0]
            n_pass, n_total = r.get("test_result") or [0, 0]
            resolved = (r.get("compile_errors", 1) == 0 and n_total > 0 and n_pass == n_total)
            return GradeResult(
                resolved=resolved,
                evaluator=_EVALUATOR_PIN,
                standard_protocol=True,
                official_report=r,
                abench={
                    "compile_errors": r.get("compile_errors"),
                    "n_pass": n_pass, "n_total": n_total,
                    "has_todo": r.get("has_todo"), "can_replace": r.get("can_replace"),
                },
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


registry.register(JavaBenchAdapter())
