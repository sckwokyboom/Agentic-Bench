import textwrap
from pathlib import Path

import pytest

from abench_ui.experiments import (
    ExperimentNotFound,
    list_experiments,
    read_experiment,
    write_experiment,
)


def _make_skeleton(root: Path, name: str) -> Path:
    exp_dir = root / name
    exp_dir.mkdir(parents=True)
    (exp_dir / "prompts").mkdir()
    (exp_dir / "slices").mkdir()
    (exp_dir / "prompts" / "task.md").write_text("do it.")
    (exp_dir / "prompts" / "system.md").write_text("be careful.")
    (exp_dir / "slices" / "graph.md").write_text("SLICE")
    (exp_dir / "original").mkdir()
    (exp_dir / "original" / "a.py").write_text("# orig")
    (exp_dir / "stripped").mkdir()
    (exp_dir / "stripped" / "a.py").write_text("# stripped")
    (exp_dir / "experiment.yaml").write_text(textwrap.dedent("""\
        name: {name}
        fixture_path: ./stripped
        reference_path: ./original
        task_prompt: ./prompts/task.md
        system_prompt: ./prompts/system.md
        model: opencode/deepseek-v4-flash-free
        repetitions: 2
        output_dir: ./runs
        conditions:
          - {{name: baseline, augmentation: null}}
          - {{name: augmented, augmentation: ./slices/graph.md}}
    """).format(name=name))
    return exp_dir


def test_list_experiments_empty(tmp_path):
    assert list_experiments(tmp_path) == []


def test_list_experiments_finds_and_summarises(tmp_path):
    _make_skeleton(tmp_path, "exp-a")
    _make_skeleton(tmp_path, "exp-b")
    items = list_experiments(tmp_path)
    names = {it["name"] for it in items}
    assert names == {"exp-a", "exp-b"}
    for it in items:
        assert it["has_fixture"] is True
        assert it["has_reference"] is True


def test_read_experiment_returns_resolved_payload(tmp_path):
    _make_skeleton(tmp_path, "exp-a")
    payload = read_experiment(tmp_path, "exp-a")
    assert payload["name"] == "exp-a"
    assert payload["task_prompt"] == "do it."
    assert payload["system_prompt"] == "be careful."
    aug = next(c for c in payload["conditions"] if c["name"] == "augmented")
    assert aug["augmentation"] == "SLICE"


def test_read_experiment_not_found(tmp_path):
    with pytest.raises(ExperimentNotFound):
        read_experiment(tmp_path, "ghost")


def test_write_experiment_atomically(tmp_path):
    _make_skeleton(tmp_path, "exp-a")
    payload = read_experiment(tmp_path, "exp-a")
    payload["repetitions"] = 5
    payload["system_prompt"] = "NEW SYSTEM PROMPT"
    write_experiment(tmp_path, "exp-a", payload)

    # System prompt was written to prompts/system.md
    assert (tmp_path / "exp-a" / "prompts" / "system.md").read_text() == "NEW SYSTEM PROMPT"
    # And experiment.yaml has the new repetitions value
    yaml_text = (tmp_path / "exp-a" / "experiment.yaml").read_text()
    assert "repetitions: 5" in yaml_text or "repetitions:5" in yaml_text
