# tests/test_libraries.py
import json
from pathlib import Path

from abench import libraries


def test_load_registry_from_explicit_file(tmp_path, monkeypatch):
    f = tmp_path / ".abench.local.json"
    f.write_text(json.dumps({"libraries": {"graph-tipper": "/opt/gt"}}))
    monkeypatch.setenv(libraries.ENV_OVERRIDE, str(f))
    assert libraries.load_registry() == {"graph-tipper": "/opt/gt"}


def test_load_registry_walks_up_from_start(tmp_path, monkeypatch):
    monkeypatch.delenv(libraries.ENV_OVERRIDE, raising=False)
    (tmp_path / ".abench.local.json").write_text(
        json.dumps({"libraries": {"x": "/p"}}))
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    assert libraries.load_registry(start=deep) == {"x": "/p"}


def test_load_registry_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.delenv(libraries.ENV_OVERRIDE, raising=False)
    assert libraries.load_registry(start=tmp_path) == {}
