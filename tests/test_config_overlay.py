import pytest
import yaml
from abench.config import load_experiment

BASE = {
    "name": "t", "fixture_path": "./fx", "reference_path": "./ref",
    "task_prompt": "do", "system_prompt": "sys", "model": "m",
    "output_dir": "./runs",
    "conditions": [{"name": "baseline", "augmentation": None}],
}

def _write(tmp_path, data):
    (tmp_path / "fx").mkdir(exist_ok=True)
    (tmp_path / "ref").mkdir(exist_ok=True)
    p = tmp_path / "experiment.yaml"
    p.write_text(yaml.safe_dump(data))
    return p

def test_overlay_resolved_relative_to_yaml_and_validated(tmp_path):
    (tmp_path / "ov").mkdir()
    data = dict(BASE)
    data["conditions"] = [{"name": "aug", "augmentation": None, "overlay": "./ov"}]
    exp = load_experiment(_write(tmp_path, data))
    assert exp.conditions[0].overlay == str((tmp_path / "ov").resolve())

def test_missing_overlay_dir_fails_at_load(tmp_path):
    data = dict(BASE)
    data["conditions"] = [{"name": "aug", "augmentation": None, "overlay": "./nope"}]
    with pytest.raises(ValueError, match="overlay"):
        load_experiment(_write(tmp_path, data))

def test_overlay_env_defaults_empty(tmp_path):
    exp = load_experiment(_write(tmp_path, dict(BASE)))
    assert exp.overlay_env == {}

def test_empty_overlay_treated_as_none(tmp_path):
    data = dict(BASE)
    data["conditions"] = [{"name": "aug", "augmentation": None, "overlay": ""}]
    exp = load_experiment(_write(tmp_path, data))
    assert exp.conditions[0].overlay is None
