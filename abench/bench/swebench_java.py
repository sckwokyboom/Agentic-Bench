"""SWE-bench-java adapter (pure-Python core).

Instance = one SWE-bench-java record. The agent gets `problem_statement` + the
repo@base_commit and must produce a source patch; grade splits the agent's diff
(source vs test), delegates the source-diff to the official multi-swe-bench
evaluator (seam `_run_swebench_evaluator`, mocked in tests), and maps the verdict
to GradeResult. Firewall (spec §2): gold `patch`, hidden `test_patch`, and
FAIL_TO_PASS/PASS_TO_PASS live ONLY in `oracle` (grade-only); the AgentView has no
oracle field. `hints_text` is never shown (issue-only fidelity).

DEFERRED to the next plan (Docker): live materialize (repo lives inside the
official image), the real `_run_swebench_evaluator` body + predictions format
(read from the pinned multi-swe-bench repo), scoped-regression, egress-lock."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from . import registry
from .base import Anchors, AgentView, EnvSpec, GradeResult, Instance, TaskSpec

# build_system per repo (verified: 5 Maven + 1 Gradle). Pilot = jackson-core (maven).
_BUILD_SYSTEM: dict[str, str] = {
    "fasterxml/jackson-databind": "maven",
    "fasterxml/jackson-core": "maven",
    "fasterxml/jackson-dataformat-xml": "maven",
    "google/gson": "maven",
    "GoogleContainerTools/jib": "gradle",
    "apache/dubbo": "maven",
}


def _image_ref(repo: str, version: str) -> str:
    """Official multi-swe-bench image ref for a repo@version. Convention isolated
    here; the EXACT registry naming is confirmed against the real images in the
    Docker plan — if it differs, adjust ONLY this function. Used only by the
    deferred Docker materialize/grade, never on the agent path."""
    slug = repo.replace("/", "_")
    return f"mswebench/{slug}:{version}"


def _as_list(value: Any) -> list[str]:
    """FAIL_TO_PASS/PASS_TO_PASS are JSON-encoded STRINGS in the dataset. Decode to
    a real list; tolerate an already-decoded list defensively."""
    if value is None:
        return []
    if isinstance(value, str):
        return list(json.loads(value))
    return list(value)


def _build_prompt(rec: dict) -> str:
    return (
        "Resolve the following issue in this repository. Edit the project's source "
        "files so the issue is fixed; do not modify test files (the evaluation "
        "provides its own tests). Work only from the repository's own code.\n\n"
        "# Issue\n" + (rec.get("problem_statement") or "").strip()
    )


class SweBenchAdapter:
    id = "swebench-java"

    def load(self, dataset: Path | None, subset: dict[str, Any] | None) -> Iterable[Instance]:
        if dataset is None:
            raise ValueError(
                "swebench-java adapter requires 'dataset' (path to swe-bench-java-verified.json)"
            )
        subset = subset or {}
        repo_filter = subset.get("repo")
        records = json.loads(Path(dataset).read_text())
        for rec in records:
            repo = rec["repo"]
            if repo_filter and repo != repo_filter:
                continue
            version = rec.get("version") or ""
            yield Instance(
                instance_id=rec["instance_id"],
                repo=repo,
                task=TaskSpec(prompt_text=_build_prompt(rec)),
                anchors=Anchors(),
                env=EnvSpec(
                    image=_image_ref(repo, version),
                    build_system=_BUILD_SYSTEM.get(repo, "maven"),
                ),
                oracle={
                    "repo": repo,
                    "base_commit": rec["base_commit"],
                    "patch": rec["patch"],
                    "test_patch": rec["test_patch"],
                    "fail_to_pass": _as_list(rec.get("FAIL_TO_PASS")),
                    "pass_to_pass": _as_list(rec.get("PASS_TO_PASS")),
                    "version": version,
                },
            )

    def materialize(self, view: AgentView, workdir: Path) -> None:  # Docker plan
        raise NotImplementedError(
            "SWE-bench-java materialize is Docker-based (repo lives inside the "
            "official image); deferred to the Docker integration plan."
        )

    def grade(self, inst: Instance, source_diff: str, workdir: Path) -> GradeResult:  # Task 3
        raise NotImplementedError


registry.register(SweBenchAdapter())
