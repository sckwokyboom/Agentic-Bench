import json
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from abench_ui.server import create_app


def _scaffold_exp(root: Path, name: str):
    d = root / name
    d.mkdir(parents=True)
    (d / "prompts").mkdir()
    (d / "slices").mkdir()
    (d / "prompts" / "task.md").write_text("do it.")
    (d / "prompts" / "system.md").write_text("be careful.")
    (d / "original").mkdir()
    (d / "original" / "a.py").write_text("x")
    (d / "stripped").mkdir()
    (d / "stripped" / "a.py").write_text("x")
    (d / "experiment.yaml").write_text(textwrap.dedent(f"""\
        name: {name}
        fixture_path: ./stripped
        reference_path: ./original
        task_prompt: ./prompts/task.md
        system_prompt: ./prompts/system.md
        model: opencode/deepseek-v4-flash-free
        repetitions: 1
        output_dir: ./runs
        conditions:
          - {{name: baseline, augmentation: null}}
    """))
    return d


@pytest.fixture
def client(tmp_path):
    app = create_app(experiments_dir=tmp_path)
    return TestClient(app), tmp_path


def test_schema_endpoint(client):
    c, _ = client
    r = c.get("/api/schema")
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "object"
    assert "name" in body["properties"]


def test_list_experiments_endpoint(client):
    c, root = client
    _scaffold_exp(root, "exp-a")
    r = c.get("/api/experiments")
    assert r.status_code == 200
    items = r.json()
    assert any(it["name"] == "exp-a" for it in items)


def test_read_experiment_endpoint(client):
    c, root = client
    _scaffold_exp(root, "exp-a")
    r = c.get("/api/experiments/exp-a")
    assert r.status_code == 200
    body = r.json()
    assert body["task_prompt"] == "do it."


def test_read_experiment_404(client):
    c, _ = client
    r = c.get("/api/experiments/ghost")
    assert r.status_code == 404


def test_read_experiment_invalid_returns_clean_error_not_500(tmp_path):
    """An experiment that exists but fails validation (e.g. its fixture_path
    doesn't resolve) must surface a clean 4xx with the reason — not a raw 500."""
    import shutil
    app = create_app(experiments_dir=tmp_path)
    c = TestClient(app, raise_server_exceptions=False)
    d = _scaffold_exp(tmp_path, "exp-bad")
    shutil.rmtree(d / "stripped")  # fixture now missing → _validate raises ValueError
    r = c.get("/api/experiments/exp-bad")
    assert r.status_code == 400, r.status_code
    assert "fixture_path" in r.text


def test_put_experiment_then_read_returns_new_values(client):
    c, root = client
    _scaffold_exp(root, "exp-a")
    payload = c.get("/api/experiments/exp-a").json()
    payload["system_prompt"] = "BRAND NEW SYSTEM"
    r = c.put("/api/experiments/exp-a", json=payload)
    assert r.status_code == 200
    payload2 = c.get("/api/experiments/exp-a").json()
    assert payload2["system_prompt"] == "BRAND NEW SYSTEM"


def test_put_experiment_422_on_pydantic_error(client):
    c, root = client
    _scaffold_exp(root, "exp-a")
    bad = c.get("/api/experiments/exp-a").json()
    bad["repetitions"] = -3  # invalid: below minimum of 1
    r = c.put("/api/experiments/exp-a", json=bad)
    assert r.status_code == 422


def test_delete_experiment(client):
    c, root = client
    _scaffold_exp(root, "exp-a")
    r = c.delete("/api/experiments/exp-a")
    assert r.status_code == 200
    assert not (root / "exp-a").exists()
    assert c.delete("/api/experiments/exp-a").status_code == 404


def test_upload_yaml_returns_payload(client):
    c, _ = client
    yaml_text = """
name: from-upload
fixture_path: ./stripped
reference_path: ./original
task_prompt: do it
system_prompt: be careful
model: opencode/deepseek-v4-flash-free
output_dir: ./runs
conditions:
  - {name: baseline, augmentation: null}
"""
    r = c.post("/api/experiments/upload", content=yaml_text,
               headers={"content-type": "application/yaml"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "from-upload"


def test_upload_yaml_invalid_422(client):
    c, _ = client
    r = c.post("/api/experiments/upload", content="not: [valid yaml",
               headers={"content-type": "application/yaml"})
    assert r.status_code == 422


def test_path_traversal_on_delete_rejected(client):
    c, _ = client
    r = c.delete("/api/experiments/..%2Fetc")
    assert r.status_code in (400, 404)


def test_path_traversal_on_read_rejected(client):
    c, _ = client
    r = c.get("/api/experiments/..%2F..%2Fetc")
    assert r.status_code in (400, 404)
