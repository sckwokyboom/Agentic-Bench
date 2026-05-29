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


def _seed_run(exp_dir: Path, name: str, condition: str, rep: int, metrics: dict) -> None:
    d = exp_dir / name / "runs" / name / condition / f"rep_{rep}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "metrics.json").write_text(json.dumps(metrics))
    (d / "manifest.json").write_text(json.dumps({"condition": condition, "rep": rep}))


def test_runs_summary_endpoint(tmp_path: Path):
    exp_dir = tmp_path / "experiments"
    base = {"interrupted_reason": None, "success": True, "n_steps": 10, "duration_s": 100.0}
    _seed_run(exp_dir, "exp", "baseline", 0, base)
    _seed_run(exp_dir, "exp", "augmented", 0, {**base, "n_steps": 5})
    app = create_app(experiments_dir=exp_dir)
    client = TestClient(app)

    resp = client.get("/api/runs/exp/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_runs"] == 2
    names = {c["name"] for c in body["conditions"]}
    assert names == {"baseline", "augmented"}
    assert body["deltas"]["n_steps"] == -50.0


def test_runs_summary_404_when_no_runs(tmp_path: Path):
    exp_dir = tmp_path / "experiments"
    (exp_dir / "exp").mkdir(parents=True)
    app = create_app(experiments_dir=exp_dir)
    client = TestClient(app)
    resp = client.get("/api/runs/exp/summary")
    assert resp.status_code == 404
