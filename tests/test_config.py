# tests/test_config.py
import textwrap
from pathlib import Path

import pytest

from abench.config import load_experiment


def _scaffold(tmp_path: Path) -> Path:
    (tmp_path / "fixture").mkdir()
    (tmp_path / "fixture" / "a.py").write_text("def f(): ...\n")
    (tmp_path / "reference").mkdir()
    (tmp_path / "reference" / "a.py").write_text("def f(): return 1\n")
    (tmp_path / "task.md").write_text("Restore the body of f().")
    (tmp_path / "system.md").write_text("You are a careful engineer.")
    (tmp_path / "slice.md").write_text("GRAPH SLICE")
    yaml_path = tmp_path / "exp.yaml"
    yaml_path.write_text(textwrap.dedent("""\
        name: exp1
        fixture_path: ./fixture
        reference_path: ./reference
        task_prompt: ./task.md
        system_prompt: ./system.md
        model: openrouter/some-model
        repetitions: 2
        output_dir: ./runs
        conditions:
          - {name: baseline, augmentation: null}
          - {name: augmented, augmentation: ./slice.md}
    """))
    return yaml_path


def test_load_resolves_text_and_paths(tmp_path):
    exp = load_experiment(_scaffold(tmp_path))
    assert exp.name == "exp1"
    assert exp.task_prompt == "Restore the body of f()."
    assert exp.system_prompt == "You are a careful engineer."
    assert exp.conditions[0].augmentation is None
    assert exp.conditions[1].augmentation == "GRAPH SLICE"
    assert exp.repetitions == 2
    assert exp.metrics.shell_tool_names == ["bash"]  # default applied


def test_missing_fixture_raises(tmp_path):
    yaml_path = _scaffold(tmp_path)
    (tmp_path / "fixture" / "a.py").unlink()
    (tmp_path / "fixture").rmdir()
    with pytest.raises(ValueError, match="fixture_path not found"):
        load_experiment(yaml_path)


def test_reference_inside_output_dir_raises(tmp_path):
    _scaffold(tmp_path)
    yaml_path = tmp_path / "exp.yaml"
    yaml_path.write_text(yaml_path.read_text().replace(
        "reference_path: ./reference", "reference_path: ./runs/reference"))
    (tmp_path / "runs" / "reference").mkdir(parents=True)
    with pytest.raises(ValueError, match="anti-leak"):
        load_experiment(yaml_path)
