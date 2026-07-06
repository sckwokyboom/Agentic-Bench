import json
from pathlib import Path

import abench.bench  # registers adapters
from abench.bench import registry


def _fake_checkout(tmp_path: Path) -> Path:
    root = tmp_path / "JavaBench"
    ds = root / "datasets" / "selective-context"
    ds.mkdir(parents=True)
    rec = {
        "task_id": "PA19/Cell.java",
        "target": "game/map/cells/Cell.java",
        "code": "```java\n// skeleton\n```",
        "code_context": "public class Coordinate { }",
    }
    (ds / "data-PA19.jsonl").write_text(json.dumps(rec) + "\n")
    (root / "projects" / "PA19" / "src" / "main" / "java" / "game" / "map" / "cells").mkdir(parents=True)
    (root / "projects" / "PA19-Solution").mkdir(parents=True)
    return root


def test_javabench_registered():
    assert "javabench" in registry.available()


def test_load_per_class_instances(tmp_path: Path):
    root = _fake_checkout(tmp_path)
    adapter = registry.get_adapter("javabench")
    insts = list(adapter.load(root, {"project": "PA19"}))
    assert len(insts) == 1
    inst = insts[0]
    assert inst.instance_id == "PA19/Cell.java"
    assert inst.repo == "javabench/PA19"
    assert inst.env.build_system == "gradle"
    assert inst.env.source_dir == str(root / "projects" / "PA19")
    # firewall: oracle carries grade-only data; agent_view has none of it
    assert inst.oracle["project_id"] == "PA19"
    assert inst.oracle["target"] == "game/map/cells/Cell.java"
    assert not hasattr(inst.agent_view(), "oracle")
    # prompt uses code_context (sanctioned), not the raw `code`
    assert "Coordinate" in inst.task.prompt_text


def test_load_requires_dataset():
    import pytest
    adapter = registry.get_adapter("javabench")
    with pytest.raises(ValueError, match="dataset"):
        list(adapter.load(None, {"project": "PA19"}))


def test_materialize_copies_skeleton_only(tmp_path: Path):
    root = _fake_checkout(tmp_path)
    # add a marker file into the skeleton and into the canonical
    (root / "projects" / "PA19" / "build.gradle").write_text("// skel\n")
    (root / "projects" / "PA19-Solution" / "SECRET.java").write_text("gold\n")
    adapter = registry.get_adapter("javabench")
    inst = list(adapter.load(root, {"project": "PA19"}))[0]

    workdir = tmp_path / "wd"
    workdir.mkdir()
    adapter.materialize(inst.agent_view(), workdir)

    assert (workdir / "build.gradle").read_text() == "// skel\n"
    # canonical/gold must NOT be present anywhere in the workdir
    assert not (workdir / "SECRET.java").exists()
    assert not any(p.name == "SECRET.java" for p in workdir.rglob("*"))
    assert not (workdir / ".git").exists()


import abench.bench.javabench as jb


def _prep_graded_instance(tmp_path):
    root = _fake_checkout(tmp_path)
    adapter = registry.get_adapter("javabench")
    inst = list(adapter.load(root, {"project": "PA19"}))[0]
    workdir = tmp_path / "wd"
    workdir.mkdir()
    # the agent's implemented class file must exist at src/main/java/<target>
    tgt = workdir / "src" / "main" / "java" / "game" / "map" / "cells" / "Cell.java"
    tgt.parent.mkdir(parents=True)
    tgt.write_text("public class Cell {}\n")
    return adapter, inst, workdir


def test_grade_resolved_when_all_tests_pass(tmp_path, monkeypatch):
    adapter, inst, workdir = _prep_graded_instance(tmp_path)
    monkeypatch.setattr(jb, "_run_javabench_grader", lambda root, preds, out: [
        {"task_id": "PA19/Cell.java", "compile_errors": 0,
         "test_result": [7, 7], "has_todo": False, "can_replace": True}])
    g = adapter.grade(inst, "diff", workdir)
    assert g.resolved is True
    assert g.standard_protocol is True
    assert g.abench["n_pass"] == 7 and g.abench["n_total"] == 7
    assert g.evaluator.startswith("javabench-class-wise")


def test_grade_not_resolved_on_partial_or_compile_error(tmp_path, monkeypatch):
    adapter, inst, workdir = _prep_graded_instance(tmp_path)
    monkeypatch.setattr(jb, "_run_javabench_grader", lambda root, preds, out: [
        {"task_id": "PA19/Cell.java", "compile_errors": 0,
         "test_result": [3, 7], "has_todo": False, "can_replace": True}])
    assert adapter.grade(inst, "diff", workdir).resolved is False

    monkeypatch.setattr(jb, "_run_javabench_grader", lambda root, preds, out: [
        {"task_id": "PA19/Cell.java", "compile_errors": 5,
         "test_result": [0, 0], "has_todo": False, "can_replace": True}])
    assert adapter.grade(inst, "diff", workdir).resolved is False


def test_run_javabench_grader_uses_sys_executable_and_cwd(tmp_path, monkeypatch):
    import sys
    calls = {}
    out_file = tmp_path / "result.json"

    def _fake_run(argv, cwd=None, check=None, **kw):
        calls["argv"] = argv
        calls["cwd"] = cwd
        out_file.write_text(json.dumps([{"task_id": "X", "test_result": [1, 1]}]))

        class _CP:  # minimal CompletedProcess stand-in
            returncode = 0
        return _CP()

    monkeypatch.setattr(jb.subprocess, "run", _fake_run)
    res = jb._run_javabench_grader("/some/root", str(tmp_path / "preds.jsonl"), str(out_file))
    assert calls["argv"][0] == sys.executable
    assert calls["cwd"] == "/some/root"
    assert res == [{"task_id": "X", "test_result": [1, 1]}]


def test_grade_writes_fenced_prediction_record(tmp_path, monkeypatch):
    adapter, inst, workdir = _prep_graded_instance(tmp_path)
    captured = {}

    def _fake(root, preds, out):
        captured.update(json.loads(Path(preds).read_text()))
        return [{"task_id": "PA19/Cell.java", "compile_errors": 0,
                 "test_result": [7, 7], "has_todo": False, "can_replace": True}]

    monkeypatch.setattr(jb, "_run_javabench_grader", _fake)
    adapter.grade(inst, "diff", workdir)
    assert captured["task_id"] == "PA19/Cell.java"
    assert captured["target"] == "game/map/cells/Cell.java"
    assert captured["completion"].startswith("```java\n")
    assert captured["completion"].rstrip().endswith("```")
    assert "public class Cell {}" in captured["completion"]
