import json
from pathlib import Path

import pytest

from abench_ui.providers import list_providers, write_credentials


def test_list_providers_reads_auth_json(tmp_path, monkeypatch):
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({
        "deepseek": {"type": "api", "key": "sk-xxx"},
        "openrouter": {"type": "api", "key": "sk-yyy"},
    }))
    monkeypatch.setattr("abench_ui.providers._auth_path", lambda: auth)
    items = list_providers()
    by_id = {it["id"]: it for it in items}
    assert by_id["deepseek"]["configured"] is True
    assert by_id["openrouter"]["configured"] is True


def test_list_providers_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr("abench_ui.providers._auth_path", lambda: tmp_path / "nope.json")
    assert list_providers() == []


def test_write_credentials_creates_file(tmp_path, monkeypatch):
    auth = tmp_path / "auth.json"
    monkeypatch.setattr("abench_ui.providers._auth_path", lambda: auth)
    write_credentials("deepseek", "sk-new")
    data = json.loads(auth.read_text())
    assert data == {"deepseek": {"type": "api", "key": "sk-new"}}


def test_write_credentials_merges_existing(tmp_path, monkeypatch):
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"openrouter": {"type": "api", "key": "sk-yyy"}}))
    monkeypatch.setattr("abench_ui.providers._auth_path", lambda: auth)
    write_credentials("deepseek", "sk-new")
    data = json.loads(auth.read_text())
    assert data["openrouter"]["key"] == "sk-yyy"
    assert data["deepseek"]["key"] == "sk-new"
