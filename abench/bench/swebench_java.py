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
from . import _msb
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


# Java/Maven/Gradle test source roots (jib uses a real src/integration-test/ Gradle
# source set; src/it is Maven's invoker convention). Matched with a leading "/" so a
# bare "src/test/..." path (no leading slash) still hits "/src/test/".
_TEST_DIR_MARKERS = ("/src/test/", "/src/integration-test/", "/src/it/")


def _is_test_path(path: str) -> bool:
    """True if a repo-relative path is a TEST file (never graded, spec §7)."""
    p = path.replace("\\", "/")
    if not p:
        return False
    q = "/" + p
    if any(m in q for m in _TEST_DIR_MARKERS):
        return True
    return p.endswith("Test.java") or p.endswith("Tests.java") or p.endswith("IT.java")


def _section_path(section: str) -> str | None:
    """The repo-relative path a single diff section targets. Robust to spaces (git
    leaves plain spaces unquoted) by reading LINE-ANCHORED markers instead of
    splitting the `diff --git` header. Returns None if no path can be resolved."""
    lines = section.splitlines()
    for line in lines:                       # modify/new file, or rename (new path)
        if line.startswith("+++ b/"):
            return line[6:].split("\t", 1)[0]
        if line.startswith("rename to "):
            return line[len("rename to "):].split("\t", 1)[0]
    for line in lines:                       # deleted file: +++ is /dev/null
        if line.startswith("--- a/"):
            return line[6:].split("\t", 1)[0]
    for line in lines:                       # fallback: minimal/degenerate diff header
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4 and parts[3].startswith("b/"):
                return parts[3][2:]
    return None


def split_source_test_diff(unified_diff: str) -> tuple[str, str]:
    """Split a unified git diff into (source_diff, test_diff) by per-file section.
    Test files (src/test | src/integration-test | src/it roots, or
    *Test.java/*Tests.java/*IT.java) go to test_diff; everything else to source_diff.
    Only source_diff is ever graded (spec §7, invariant 2).

    FIREWALL SAFETY: a section whose path cannot be resolved defaults to test_diff
    (excluded from grading) — an unclassifiable edit is NEVER silently leaked into
    the graded bucket."""
    if not unified_diff.strip():
        return "", ""
    sections: list[str] = []
    current: list[str] = []
    for line in unified_diff.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current:
                sections.append("".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append("".join(current))

    source_parts: list[str] = []
    test_parts: list[str] = []
    for section in sections:
        path = _section_path(section)
        is_test = path is None or _is_test_path(path)   # unresolved → safe (test)
        (test_parts if is_test else source_parts).append(section)
    return "".join(source_parts), "".join(test_parts)


_EVALUATOR_PIN = "multi-swe-bench@<pin-set-in-docker-plan>"


def _run_swebench_evaluator(oracle: dict, source_diff: str) -> dict:
    """Delegate to the official multi-swe-bench evaluator in a clean, OFFLINE
    grading container: apply `source_diff` + the oracle's own `test_patch` to a
    pristine checkout at `base_commit`, run FAIL_TO_PASS/PASS_TO_PASS, return the
    raw report incl. a top-level `resolved: bool`. Isolated so tests monkeypatch it.

    DEFERRED (Docker plan): the real body. IMPLEMENTER of the Docker plan MUST read
    the pinned multi-swe-bench repo to confirm the exact predictions-file format and
    CLI/entry (spec §10 open question), set `_EVALUATOR_PIN` to the pinned digest,
    and run it with no network (offline determinism, spec §7)."""
    raise NotImplementedError(
        "live SWE-bench-java grading is Docker-based; deferred to the Docker plan"
    )


def _run_abench_verify(oracle: dict, source_diff: str, test_diff: str, workdir: Path) -> dict:
    """abench's OWN grading methodology — run ALONGSIDE the official verdict (spec
    §7), the same kind abench already runs on the putValue experiment. The official
    criterion has NO regression guard (PASS_TO_PASS empty) — this is what abench
    adds. Returns {scoped_regressions: list[str], repro_reproduced: bool,
    abench_resolved: bool|None}. Isolated so tests monkeypatch it.

    DEFERRED (Docker plan): the real body = in a clean container, apply the
    source-fix, run the BLAST-RADIUS tests (touched methods → covering tests via the
    graph/Joern, spec §7) before/after to find regressions; re-run the agent's own
    repro (from test_diff) on base for repro_reproduced; abench_resolved = abench's
    own FAIL_TO_PASS pass/fail cross-check. Docker + graph gated."""
    raise NotImplementedError(
        "abench's own SWE verify/regression is Docker+graph-based; deferred to the Docker plan"
    )


class SweBenchAdapter:
    id = "swebench-java"

    def load(self, dataset: Path | None, subset: dict[str, Any] | None) -> Iterable[Instance]:
        if dataset is None:
            raise ValueError(
                "swebench-java adapter requires 'dataset' (native Multi-SWE-bench JSONL)"
            )
        subset = subset or {}
        repo_filter = subset.get("repo")
        msb_root = subset.get("msb_root")   # path to the pinned multi-swe-bench checkout (grade needs it)
        for line in Path(dataset).read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if repo_filter and _msb.display_repo(rec) != repo_filter:
                continue
            yield Instance(
                instance_id=_msb.instance_id(rec),
                repo=_msb.display_repo(rec),
                task=TaskSpec(prompt_text=(
                    "Resolve the following issue in this repository. Edit the project's "
                    "SOURCE files so the issue is fixed; do not modify test files (the "
                    "evaluation provides its own). Work only from the repo's own code.\n\n"
                    "# Issue\n" + _msb.issue_text(rec))),
                anchors=Anchors(),
                env=EnvSpec(
                    image=_msb.image_ref(rec),
                    build_system=_BUILD_SYSTEM.get(_msb.display_repo(rec), "maven"),
                ),
                oracle={
                    "record": rec,                 # full native record → the grader writes it back verbatim
                    "base_sha": _msb.base_sha(rec),
                    "fix_patch": rec["fix_patch"],
                    "test_patch": rec["test_patch"],
                    "f2p_tests": rec.get("f2p_tests") or {},
                    "msb_root": msb_root,
                },
            )

    def materialize(self, view: AgentView, workdir: Path) -> None:  # Docker plan
        raise NotImplementedError(
            "SWE-bench-java materialize is Docker-based (repo lives inside the "
            "official image); deferred to the Docker integration plan."
        )

    def grade(self, inst: Instance, source_diff: str, workdir: Path) -> GradeResult:
        # `source_diff` here is the agent's FULL workdir diff (protocol name). Split
        # it: only the source part is graded; the agent's own test edits are kept
        # for abench stats but NEVER sent to the evaluator (spec §7, invariant 2).
        src_diff, test_diff = split_source_test_diff(source_diff)
        # (1) OFFICIAL verdict — the comparable, exported number (spec §3).
        official = _run_swebench_evaluator(inst.oracle, src_diff)
        # (2) abench's OWN methodology — regressions/repro the official criterion
        # omits (spec §7). Co-equal, but NEVER the exported SWE number.
        own = _run_abench_verify(inst.oracle, src_diff, test_diff, workdir)
        return GradeResult(
            resolved=bool(official.get("resolved")),      # headline = OFFICIAL only
            evaluator=_EVALUATOR_PIN,
            standard_protocol=True,
            official_report=official,
            abench={
                **own,                                      # scoped_regressions, repro_reproduced, abench_resolved
                "test_diff_present": bool(test_diff.strip()),
                "n_fail_to_pass": len(inst.oracle.get("f2p_tests") or {}),
            },
        )


registry.register(SweBenchAdapter())
