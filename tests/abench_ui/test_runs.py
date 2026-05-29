import json
from pathlib import Path

import pytest

from abench_ui.runs import (
    RunNotFound,
    _rundir,
    list_runs,
    method_comparison,
    patch_success,
    read_artefact,
)


def _make_run(root: Path, name: str, cond: str, rep: int, *, success=None):
    rundir = root / name / cond / f"rep_{rep}"
    rundir.mkdir(parents=True)
    (rundir / "manifest.json").write_text(json.dumps({
        "condition": cond, "rep": rep, "model": "m",
    }))
    (rundir / "metrics.json").write_text(json.dumps({
        "n_steps": 4, "n_tool_calls": 3, "verify_status": "passed",
        "verify_passed_count": 10, "success": success,
        "finished": True, "interrupted_reason": None,
    }))
    (rundir / "trace.json").write_text(json.dumps({"steps": [], "turns": []}))
    (rundir / "events.jsonl").write_text('{"type":"ping"}\n')
    (rundir / "changes.patch").write_text("diff --git a/x b/x\n--- a/x\n+++ b/x\n+hi\n")
    return rundir


def test_list_runs(tmp_path):
    root = tmp_path / "exp-a" / "runs"
    _make_run(root, "x", "baseline", 0)
    _make_run(root, "x", "augmented", 1)
    items = list_runs(root / "x")
    keys = {(it["condition"], it["rep"]) for it in items}
    assert keys == {("baseline", 0), ("augmented", 1)}


def test_read_artefact(tmp_path):
    root = tmp_path / "exp" / "runs"
    _make_run(root, "x", "baseline", 0)
    metrics = read_artefact(root / "x", "baseline", 0, "metrics.json")
    assert json.loads(metrics)["n_steps"] == 4


def test_read_artefact_missing(tmp_path):
    with pytest.raises(RunNotFound):
        read_artefact(tmp_path / "no-such" / "x", "baseline", 0, "metrics.json")


def test_patch_success(tmp_path):
    root = tmp_path / "exp" / "runs"
    _make_run(root, "x", "baseline", 0)
    updated = patch_success(root / "x", "baseline", 0, success=True)
    assert updated["success"] is True
    # And it persisted on disk:
    assert json.loads(
        (root / "x" / "baseline" / "rep_0" / "metrics.json").read_text()
    )["success"] is True


def test_rundir_rejects_path_traversal(tmp_path):
    (tmp_path / "exp" / "runs" / "x" / "baseline" / "rep_0").mkdir(parents=True)
    with pytest.raises(RunNotFound):
        _rundir(tmp_path / "exp" / "runs" / "x", "../../../etc", 0)


def test_method_comparison_python(tmp_path):
    # Build a tiny reference + workdir that diverged in one method body
    ref = tmp_path / "ref"
    ref.mkdir()
    (ref / "mod.py").write_text(
        "def foo(x):\n    return x + 1\n\ndef bar():\n    return 2\n"
    )
    # Simulate "regenerated" file: same as original (semantically equivalent)
    wkdir = tmp_path / "wk"
    wkdir.mkdir()
    (wkdir / "mod.py").write_text(
        "def foo(x):\n    return x + 1\n\ndef bar():\n    return 2\n"
    )
    result = method_comparison(
        reference_dir=ref, workdir=wkdir,
        target_file="mod.py", method_name="foo",
    )
    assert result["method_name"] == "foo"
    assert "return x + 1" in "\n".join(result["original_lines"])
    assert "return x + 1" in "\n".join(result["regen_lines"])
    assert result["equivalent"] is True
