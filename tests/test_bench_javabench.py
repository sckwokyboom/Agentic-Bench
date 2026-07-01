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
