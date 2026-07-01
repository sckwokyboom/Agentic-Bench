"""A trivial in-repo adapter for wiring/integration tests. No Docker, no network,
no external dataset — one instance whose task is to implement add(a, b)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from . import registry
from .base import AgentView, Anchors, EnvSpec, GradeResult, Instance, TaskSpec


class SmokeAdapter:
    id = "smoke"

    def load(self, dataset: Path | None = None, subset: dict[str, Any] | None = None) -> Iterable[Instance]:
        yield Instance(
            instance_id="smoke-1",
            repo="smoke",
            task=TaskSpec(prompt_text="Make add(a, b) return a + b in calc.py"),
            anchors=Anchors(existing_tests=("test_add",)),
            env=EnvSpec(image="none", build_system="none"),
            oracle={
                "gold_patch": "def add(a, b): return a + b",
                "hidden_test_patch": "assert add(1, 2) == 3",
            },
        )

    def materialize(self, view: AgentView, workdir: Path) -> None:
        (workdir / "calc.py").write_text("def add(a, b):\n    raise NotImplementedError\n")
        (workdir / "task.md").write_text(view.task.prompt_text + "\n")

    def grade(self, inst: Instance, source_diff: str, workdir: Path) -> GradeResult:
        namespace: dict[str, Any] = {}
        resolved = False
        try:
            exec((workdir / "calc.py").read_text(), namespace)
            add = namespace.get("add")
            resolved = callable(add) and add(1, 2) == 3
        except Exception:
            resolved = False
        return GradeResult(
            resolved=bool(resolved),
            evaluator="smoke@1",
            standard_protocol=True,
            abench={"made_source_changes": bool(source_diff.strip())},
        )


registry.register(SmokeAdapter())
