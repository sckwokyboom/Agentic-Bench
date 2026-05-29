from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from abench_ui.server import create_app


@pytest.fixture
def app_with_static(tmp_path: Path):
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html><body>SPA</body></html>")
    (static_dir / "assets").mkdir()
    (static_dir / "assets" / "x.js").write_text("console.log('hi');")
    exp_dir = tmp_path / "experiments"
    exp_dir.mkdir()
    return create_app(experiments_dir=exp_dir, static_dir=static_dir)


def test_serves_index_html_at_root(app_with_static):
    client = TestClient(app_with_static)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "SPA" in resp.text


def test_serves_assets(app_with_static):
    client = TestClient(app_with_static)
    resp = client.get("/assets/x.js")
    assert resp.status_code == 200
    assert "console.log" in resp.text


def test_unknown_route_falls_back_to_index(app_with_static):
    """Client-side router paths should still resolve to index.html on reload."""
    client = TestClient(app_with_static)
    resp = client.get("/runs/sessions/abc123")
    assert resp.status_code == 200
    assert "SPA" in resp.text


def test_api_path_does_not_fall_back(app_with_static):
    """API 404s must remain API 404s — never bleed into the SPA fallback."""
    client = TestClient(app_with_static)
    resp = client.get("/api/experiments/does-not-exist")
    assert resp.status_code == 404
    assert "detail" in resp.json()


def test_path_traversal_outside_static_is_refused(tmp_path):
    """A URL-encoded ../ escape must NOT serve a file outside static_dir.

    The traversal target resolves to a real file the server could otherwise
    read; the containment guard must fall back to index.html instead."""
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html><body>SPA</body></html>")
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP SECRET")
    exp_dir = tmp_path / "experiments"
    exp_dir.mkdir()
    app = create_app(experiments_dir=exp_dir, static_dir=static_dir)
    client = TestClient(app)
    # ../secret.txt relative to static/ resolves to the sibling secret file.
    resp = client.get("/..%2Fsecret.txt")
    assert resp.status_code == 200
    assert "TOP SECRET" not in resp.text   # served index.html, not the secret
    assert "SPA" in resp.text
