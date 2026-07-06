"""SWE-bench-java adapter (native Multi-SWE-bench schema).

Instance = one native Multi-SWE-bench record (org/repo/number). The agent gets the
issue text (`_msb.issue_text`: title + body + resolved_issues) + the repo@base.sha
and must produce a SOURCE patch; grade splits the agent's diff (source vs test),
delegates the source-diff to the official multi-swe-bench evaluator (seam
`_run_swebench_evaluator`) AND to abench's own methodology (seam `_run_abench_verify`),
mapping both to GradeResult. Firewall (spec §2): gold `fix_patch`, hidden `test_patch`
/`f2p_tests`, and the full native `record` live ONLY in `oracle` (grade-only); the
AgentView has no oracle field. `hints` (native, gold-fix-derived) is never read.

The live grade + materialize need Docker + the official image + a pinned multi-swe-bench
checkout (Plan 4b); the pure parts are unit-tested with fixtures/mocks."""
from __future__ import annotations

import json
import shutil
import tempfile
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
    """Official verdict: run the pinned multi-swe-bench evaluator on the candidate's
    SOURCE diff (as `fix_patch`) against the instance's native dataset record, and
    map the result to {resolved, report}. The candidate submits ONLY the source-diff
    (the dataset's own test_patch is baked into the image) — spec §7 / invariant 2.
    The subprocess/harness call is isolated in `_msb.run_evaluation` (mocked in tests;
    the live call needs Docker + the pulled official image)."""
    rec = oracle["record"]
    msb_root = oracle.get("msb_root")
    if not msb_root:
        raise ValueError(
            "swebench-java grade requires subset['msb_root'] "
            "(path to the pinned multi-swe-bench checkout)"
        )
    iid = _msb.instance_id(rec)
    tmp = Path(tempfile.mkdtemp(prefix="abench-msb-grade-"))
    try:
        out_dir = tmp / "output"
        for d in (out_dir, tmp / "work", tmp / "logs", tmp / "repos"):
            d.mkdir()
        dataset = tmp / "dataset.jsonl"
        preds = tmp / "preds.jsonl"
        dataset.write_text(json.dumps(rec) + "\n")
        preds.write_text(json.dumps(_msb.prediction_record(rec, source_diff)) + "\n")
        config = {
            "mode": "evaluation",
            "workdir": str(tmp / "work"),
            "log_dir": str(tmp / "logs"),
            "output_dir": str(out_dir),
            "repo_dir": str(tmp / "repos"),      # HOST(Task 5): confirm build/repo_dir semantics
            "patch_files": [str(preds)],
            "dataset_files": [str(dataset)],
            "specifics": [iid],
            "need_clone": False,
            "force_build": False,
        }
        report = _msb.run_evaluation(msb_root, config, str(out_dir))
        instance_report = _msb.find_instance_report(str(tmp / "work"))
        return {
            "resolved": iid in (report.get("resolved_ids") or []),
            "report": report,
            "instance_report": instance_report,
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run_abench_verify(oracle: dict, instance_report: dict, test_diff: str) -> dict:
    """abench's OWN methodology v1 (spec §7) — mine the harness's per-instance report
    for what the official empty-PASS_TO_PASS criterion omits: regressions + repro.
    v1 READS the harness report (no separate run); the Joern blast-radius scoping of
    which tests to weight is a deferred enhancement. HOST(Task 5): confirm the report
    key shapes (p2p_tests/f2p_tests dicts of {run,test,fix}; `valid` flag)."""
    regressions: list[str] = []
    for key in ("p2p_tests", "f2p_tests", "s2p_tests", "n2p_tests"):
        for name, st in (instance_report.get(key) or {}).items():
            if isinstance(st, dict) and st.get("test") == "PASS" and st.get("fix") == "FAIL":
                regressions.append(name)
    # repro signal: did the instance's known fail-to-pass tests actually fail at the
    # test stage (test_patch only)? (from the dataset's f2p_tests in oracle)
    f2p = oracle.get("f2p_tests") or {}
    repro_reproduced = any(
        isinstance(st, dict) and st.get("test") == "FAIL" for st in f2p.values()
    )
    return {
        "scoped_regressions": sorted(set(regressions)),
        "repro_reproduced": repro_reproduced,
        "abench_resolved": instance_report.get("valid"),   # harness's own verdict (bool|None)
    }


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

    def materialize(self, view: AgentView, workdir: Path) -> None:
        # The official image has the repo checked out at base.sha under /home/<repo>.
        # Extract it to the agent's workdir, then strip VCS history.
        repo_name = view.repo.split("/")[-1]
        _msb._docker_cp_repo(view.env.image, f"/home/{repo_name}", str(workdir))
        gitdir = Path(workdir) / ".git"
        if gitdir.exists():
            shutil.rmtree(gitdir)

    def grade(self, inst: Instance, source_diff: str, workdir: Path) -> GradeResult:
        # `source_diff` here is the agent's FULL workdir diff (protocol name). Split
        # it: only the source part is graded; the agent's own test edits are kept
        # for abench stats but NEVER sent to the evaluator (spec §7, invariant 2).
        src_diff, test_diff = split_source_test_diff(source_diff)
        # (1) OFFICIAL verdict — the comparable, exported number (spec §3).
        official = _run_swebench_evaluator(inst.oracle, src_diff)
        # (2) abench's OWN methodology — regressions/repro the official criterion
        # omits (spec §7). Co-equal, but NEVER the exported SWE number.
        own = _run_abench_verify(inst.oracle, official.get("instance_report") or {}, test_diff)
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
