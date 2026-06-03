"""Model catalog: list_model_catalog() helper + GET /api/models endpoint.

The endpoint must degrade gracefully (return [] with HTTP 200, never 500)
when the underlying opencode CLI is unavailable or raises.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from abench_ui import validate as validate_mod
from abench_ui.server import create_app


@pytest.fixture
def client(tmp_path: Path):
    exp_dir = tmp_path / "experiments"
    exp_dir.mkdir()
    app = create_app(experiments_dir=exp_dir)
    return TestClient(app)


def test_list_model_catalog_flattens_providers(monkeypatch):
    monkeypatch.setattr(validate_mod, "_providers", lambda: {"openrouter", "deepseek"})

    def _models(provider: str):
        if provider == "openrouter":
            return ["openrouter/x", "openrouter/y"]
        if provider == "deepseek":
            return ["deepseek/deepseek-chat"]
        return []

    monkeypatch.setattr(validate_mod, "_models", _models)
    catalog = validate_mod.list_model_catalog()
    assert {"provider": "deepseek", "id": "deepseek/deepseek-chat"} in catalog
    assert {"provider": "openrouter", "id": "openrouter/x"} in catalog
    assert {"provider": "openrouter", "id": "openrouter/y"} in catalog
    assert len(catalog) == 3


def test_models_endpoint_returns_catalog(client, monkeypatch):
    monkeypatch.setattr(validate_mod, "_providers", lambda: {"openrouter"})
    monkeypatch.setattr(validate_mod, "_models", lambda p: ["openrouter/x"])
    resp = client.get("/api/models")
    assert resp.status_code == 200
    assert resp.json() == [{"provider": "openrouter", "id": "openrouter/x"}]


def test_models_endpoint_degrades_to_empty_on_error(client, monkeypatch):
    def _boom():
        raise RuntimeError("opencode CLI not found")

    monkeypatch.setattr(validate_mod, "list_model_catalog", _boom)
    resp = client.get("/api/models")
    assert resp.status_code == 200
    assert resp.json() == []
