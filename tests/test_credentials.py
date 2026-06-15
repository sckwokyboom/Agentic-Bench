import json
from pathlib import Path

from abench import credentials


def _write_auth(tmp_path, data):
    d = tmp_path / "opencode"
    d.mkdir(parents=True, exist_ok=True)
    (d / "auth.json").write_text(json.dumps(data), encoding="utf-8")


def test_read_credential_present(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    _write_auth(tmp_path, {"deepseek": {"type": "api", "key": "sk-secret"}})
    assert credentials.read_credential("deepseek") == "sk-secret"
    assert credentials.has_credential("deepseek") is True


def test_read_credential_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    _write_auth(tmp_path, {"other": {"type": "api", "key": "x"}})
    assert credentials.read_credential("deepseek") is None
    assert credentials.has_credential("deepseek") is False


def test_read_credential_no_file(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert credentials.read_credential("deepseek") is None


class _Prov:
    def __init__(self, id, api_key_env):
        self.id = id
        self.api_key_env = api_key_env


def test_run_env_overlays_authjson_when_env_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    _write_auth(tmp_path, {"deepseek": {"type": "api", "key": "sk-fromauth"}})
    env = credentials.run_env([_Prov("deepseek", "DEEPSEEK_API_KEY")])
    assert env["DEEPSEEK_API_KEY"] == "sk-fromauth"


def test_run_env_os_env_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-fromenv")
    _write_auth(tmp_path, {"deepseek": {"type": "api", "key": "sk-fromauth"}})
    env = credentials.run_env([_Prov("deepseek", "DEEPSEEK_API_KEY")])
    assert env["DEEPSEEK_API_KEY"] == "sk-fromenv"
