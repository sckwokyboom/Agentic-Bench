from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from abench_ui.server import create_app


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(experiments_dir=tmp_path)), tmp_path


def test_verify_augmentation_found_absolute(client):
    c, tmp = client
    f = tmp / "slice.md"
    f.write_text("first line\nsecond line\n")
    r = c.post("/api/augmentation/verify", json={"path": str(f)})
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is True
    assert body["size"] == f.stat().st_size
    assert body["preview"].startswith("first line")


def test_verify_augmentation_missing(client):
    c, _ = client
    r = c.post("/api/augmentation/verify", json={"path": "/no/such/file.md"})
    assert r.status_code == 200
    assert r.json()["found"] is False


def test_verify_augmentation_relative_with_name(client):
    # The primary use case: a file-kind path relative to the experiment dir.
    c, tmp = client
    exp_dir = tmp / "my-exp"
    (exp_dir / "slices").mkdir(parents=True)
    (exp_dir / "slices" / "aug.md").write_text("slice content")
    r = c.post("/api/augmentation/verify",
               json={"path": "slices/aug.md", "name": "my-exp"})
    body = r.json()
    assert body["found"] is True
    assert body["preview"].startswith("slice content")


def test_model_context_returns_window(client, monkeypatch):
    c, _ = client
    import abench_ui.server as srv
    monkeypatch.setattr(srv, "fetch_context_window", lambda *a, **k: 131072)
    r = c.post("/api/model/context",
               json={"model": "vllm/qwen", "base_url": "http://h/v1"})
    assert r.status_code == 200
    assert r.json()["context_window"] == 131072


def test_model_context_none_on_failure(client, monkeypatch):
    c, _ = client
    import abench_ui.server as srv
    monkeypatch.setattr(srv, "fetch_context_window", lambda *a, **k: None)
    r = c.post("/api/model/context", json={"model": "m", "base_url": ""})
    assert r.json()["context_window"] is None
