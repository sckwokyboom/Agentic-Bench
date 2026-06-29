import textwrap
from pathlib import Path

import pytest

from abench_ui.experiments import (
    ExperimentNotFound,
    _relpath,
    list_experiments,
    read_experiment,
    write_experiment,
)


def test_relpath_keeps_a_relative_input_relative(tmp_path):
    """A relative path (as produced by uploading a yaml, where the server never
    sees the file's original location) must stay relative to the experiment dir
    — NOT get resolved against the server CWD (which pointed it at the project
    root: fixture_path '/<project>/stripped')."""
    exp = tmp_path / "exp-x"
    assert _relpath("./stripped", exp) == "./stripped"
    assert _relpath("stripped", exp) == "./stripped"


def test_relpath_absolute_under_expdir_becomes_relative(tmp_path):
    exp = tmp_path / "exp-x"
    exp.mkdir()
    assert _relpath(str(exp / "stripped"), exp) == "./stripped"


def test_relpath_absolute_outside_expdir_stays_absolute(tmp_path):
    exp = tmp_path / "exp-x"
    exp.mkdir()
    outside = (tmp_path / "elsewhere" / "stripped")
    assert _relpath(str(outside), exp) == str(outside.resolve())


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


def test_system_augmentation_round_trips_as_md_ref(tmp_path):
    """A condition's system_augmentation must externalise to slices/<name>-system.md
    on write (NOT inline its text into the YAML — an inlined multi-line blob is
    then mis-stat'd as a path and 500s read_experiment)."""
    import yaml as _yaml
    exp_dir = _make_skeleton(tmp_path, "exp-a")
    (exp_dir / "slices" / "fi.md").write_text("METHODOLOGY")
    (exp_dir / "slices" / "fi-sys.md").write_text("SYS\nLINE2\nLINE3")
    yaml_p = exp_dir / "experiment.yaml"
    data = _yaml.safe_load(yaml_p.read_text())
    data["conditions"].append({
        "name": "forced-instrument",
        "augmentation": "./slices/fi.md",
        "system_augmentation": "./slices/fi-sys.md",
        "restore_non_target_before_verify": True,
    })
    yaml_p.write_text(_yaml.safe_dump(data, sort_keys=False))

    payload = read_experiment(tmp_path, "exp-a")           # resolves to text
    fi = next(c for c in payload["conditions"] if c["name"] == "forced-instrument")
    assert fi["system_augmentation"] == "SYS\nLINE2\nLINE3"
    assert fi["restore_non_target_before_verify"] is True

    write_experiment(tmp_path, "exp-a", payload)           # must re-externalise
    yaml_text = (exp_dir / "experiment.yaml").read_text()
    assert "./slices/forced-instrument-system.md" in yaml_text
    assert "LINE2" not in yaml_text                        # text NOT inlined into yaml
    assert (exp_dir / "slices" / "forced-instrument-system.md").read_text() == "SYS\nLINE2\nLINE3"

    payload2 = read_experiment(tmp_path, "exp-a")          # round-trips cleanly
    fi2 = next(c for c in payload2["conditions"] if c["name"] == "forced-instrument")
    assert fi2["system_augmentation"] == "SYS\nLINE2\nLINE3"
    assert fi2["restore_non_target_before_verify"] is True


def test_read_survives_inlined_system_augmentation(tmp_path):
    """Defence in depth: even if the YAML already has system_augmentation inlined
    as multi-line text (e.g. saved by an older UI build), read must not 500 —
    the loader returns the text verbatim instead of stat-ing it as a path."""
    exp_dir = _make_skeleton(tmp_path, "exp-a")
    blob = "do X\n" * 500                                  # multi-line, > NAME_MAX
    import yaml as _yaml
    data = _yaml.safe_load((exp_dir / "experiment.yaml").read_text())
    data["conditions"].append({"name": "fi", "system_augmentation": blob})
    (exp_dir / "experiment.yaml").write_text(_yaml.safe_dump(data))
    payload = read_experiment(tmp_path, "exp-a")           # must not raise
    fi = next(c for c in payload["conditions"] if c["name"] == "fi")
    assert fi["system_augmentation"] == blob


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
