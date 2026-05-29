import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from abench_ui.server import create_app


def _make_runs(root: Path):
    name = "exp-a"
    rd = root / name / "runs" / name / "baseline" / "rep_0"
    rd.mkdir(parents=True)
    (rd / "manifest.json").write_text(json.dumps({"condition": "baseline", "rep": 0}))
    (rd / "metrics.json").write_text(json.dumps({
        "n_steps": 4, "verify_status": "passed",
        "verify_passed_count": 10, "success": None,
        "finished": True, "interrupted_reason": None,
    }))
    (rd / "trace.json").write_text(json.dumps({"steps": [], "turns": []}))
    (rd / "changes.patch").write_text("diff --git a/x b/x\n--- a/x\n+++ b/x\n+1\n")
    (rd / "events.jsonl").write_text('{"type":"ping"}\n')
    # also scaffold the experiment.yaml so /api/experiments/{name} works
    (root / name / "experiment.yaml").write_text("name: exp-a\nfixture_path: ./stripped\n")


@pytest.fixture
def client(tmp_path):
    app = create_app(experiments_dir=tmp_path)
    return TestClient(app), tmp_path


def test_list_runs_endpoint(client):
    c, root = client
    _make_runs(root)
    r = c.get("/api/runs/exp-a")
    assert r.status_code == 200
    items = r.json()
    assert any(it["condition"] == "baseline" and it["rep"] == 0 for it in items)


def test_read_run_artefacts(client):
    c, root = client
    _make_runs(root)
    r = c.get("/api/runs/exp-a/baseline/0/metrics")
    assert r.status_code == 200
    assert r.json()["n_steps"] == 4
    r = c.get("/api/runs/exp-a/baseline/0/trace")
    assert r.json() == {"steps": [], "turns": []}
    r = c.get("/api/runs/exp-a/baseline/0/patch")
    assert "diff --git" in r.text


def test_patch_success(client):
    c, root = client
    _make_runs(root)
    r = c.patch("/api/runs/exp-a/baseline/0", json={"success": True})
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_read_events_endpoint(client):
    c, root = client
    _make_runs(root)
    r = c.get("/api/runs/exp-a/baseline/0/events")
    assert r.status_code == 200
    assert "ping" in r.text  # the helper writes {"type":"ping"} to events.jsonl
