import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from abench_ui import validate as validate_mod
from abench_ui.providers import list_providers, write_credentials
from abench_ui.server import create_app


def test_list_providers_reads_auth_json(tmp_path, monkeypatch):
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({
        "deepseek": {"type": "api", "key": "sk-xxx"},
        "openrouter": {"type": "api", "key": "sk-yyy"},
    }))
    monkeypatch.setattr("abench_ui.providers.auth_path", lambda: auth)
    items = list_providers()
    by_id = {it["id"]: it for it in items}
    assert by_id["deepseek"]["configured"] is True
    assert by_id["openrouter"]["configured"] is True


def test_list_providers_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr("abench_ui.providers.auth_path", lambda: tmp_path / "nope.json")
    assert list_providers() == []


def test_write_credentials_creates_file(tmp_path, monkeypatch):
    auth = tmp_path / "auth.json"
    monkeypatch.setattr("abench_ui.providers.auth_path", lambda: auth)
    write_credentials("deepseek", "sk-new")
    data = json.loads(auth.read_text())
    assert data == {"deepseek": {"type": "api", "key": "sk-new"}}


def test_write_credentials_merges_existing(tmp_path, monkeypatch):
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"openrouter": {"type": "api", "key": "sk-yyy"}}))
    monkeypatch.setattr("abench_ui.providers.auth_path", lambda: auth)
    write_credentials("deepseek", "sk-new")
    data = json.loads(auth.read_text())
    assert data["openrouter"]["key"] == "sk-yyy"
    assert data["deepseek"]["key"] == "sk-new"


def test_credentials_endpoint_clears_validate_caches(tmp_path, monkeypatch):
    """Writing a key must invalidate the validate TTL caches so the UI's
    model chip re-validates immediately instead of showing a stale 'no key'
    for up to 30s."""
    auth = tmp_path / "auth.json"
    monkeypatch.setattr("abench_ui.providers.auth_path", lambda: auth)

    # Seed the caches with stale data (simulate a prior validate call).
    validate_mod._PROVIDERS_CACHE[()] = {"opencode"}
    validate_mod._MODELS_CACHE["deepseek"] = ["deepseek/deepseek-chat"]
    assert len(validate_mod._PROVIDERS_CACHE) == 1
    assert len(validate_mod._MODELS_CACHE) == 1

    exp_dir = tmp_path / "experiments"
    exp_dir.mkdir()
    client = TestClient(create_app(experiments_dir=exp_dir))
    resp = client.post("/api/providers/deepseek/credentials",
                       json={"api_key": "sk-new"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    # Both caches were cleared, so the next validate() re-invokes the CLI.
    assert len(validate_mod._PROVIDERS_CACHE) == 0
    assert len(validate_mod._MODELS_CACHE) == 0
