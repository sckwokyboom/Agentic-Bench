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


def test_load_experiment_defaults_for_new_fields(tmp_path):
    yaml_path = _scaffold(tmp_path)
    exp = load_experiment(yaml_path)
    # verify defaults
    assert exp.verify.enabled is True
    assert exp.verify.timeout_s == 300
    assert exp.verify.command is None
    # isolation defaults: both lightweight mechanisms ON
    assert exp.isolation.nonce_prefix is True
    assert exp.isolation.shuffle_order is True
    assert exp.isolation.user_field_template is None
    # target defaults: optional, both None
    assert exp.target_file is None
    assert exp.target_methods is None
    # run timeout: no limit by default (the agent can take as long as it needs)
    assert exp.timeout_s is None


def test_timeout_s_defaults_to_no_limit_and_accepts_a_number(tmp_path):
    yaml_path = _scaffold(tmp_path)
    assert load_experiment(yaml_path).timeout_s is None
    yaml_path.write_text(yaml_path.read_text() + "\ntimeout_s: 1800\n")
    assert load_experiment(yaml_path).timeout_s == 1800


def test_load_experiment_accepts_verify_and_isolation_blocks(tmp_path):
    yaml_path = _scaffold(tmp_path)
    yaml_path.write_text(yaml_path.read_text() + """
verify:
  command: ./gradlew test
  timeout_s: 600
  enabled: true
isolation:
  nonce_prefix: false
  shuffle_order: true
""")
    exp = load_experiment(yaml_path)
    assert exp.verify.command == "./gradlew test"
    assert exp.verify.timeout_s == 600
    assert exp.isolation.nonce_prefix is False
    assert exp.isolation.shuffle_order is True


def test_target_file_must_exist_relative_to_fixture(tmp_path):
    _scaffold(tmp_path)
    yaml_path = tmp_path / "exp.yaml"
    yaml_path.write_text(yaml_path.read_text() + "\ntarget_file: a.py\n")
    # a.py exists in the fixture from _scaffold — ok
    exp = load_experiment(yaml_path)
    assert exp.target_file == "a.py"

    yaml_path.write_text(yaml_path.read_text().replace("a.py", "missing.py"))
    with pytest.raises(ValueError, match="target_file"):
        load_experiment(yaml_path)


def test_condition_temperature_parses_and_defaults(tmp_path):
    from abench.config import Condition
    assert Condition(name="c").temperature is None
    assert Condition(name="c", temperature=0.7).temperature == 0.7


def test_condition_temperature_out_of_range_rejected():
    from abench.config import Condition
    with pytest.raises(Exception):
        Condition(name="c", temperature=2.5)
    with pytest.raises(Exception):
        Condition(name="c", temperature=-0.1)
