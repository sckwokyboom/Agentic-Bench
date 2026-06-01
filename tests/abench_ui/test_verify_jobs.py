import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from abench_ui.server import create_app


def _seed_experiment(exp_dir: Path):
    d = exp_dir / "exp"
    (d / "fix").mkdir(parents=True)
    (d / "fix" / "a.txt").write_text("old\n")
    rd = d / "runs" / "exp" / "baseline" / "rep_0"
    rd.mkdir(parents=True)
    patch = ("diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n")
    (rd / "changes.patch").write_text(patch)
    (rd / "metrics.json").write_text(json.dumps({"verify_status": "error", "success": None}))
    (rd / "trace.json").write_text(json.dumps({"steps": [], "turns": []}))
    (d / "prompts").mkdir()
    (d / "prompts" / "task.md").write_text("t")
    (d / "prompts" / "system.md").write_text("s")
    (d / "experiment.yaml").write_text(
        "name: exp\nfixture_path: ./fix\nreference_path: ./fix\n"
        "task_prompt: ./prompts/task.md\nsystem_prompt: ./prompts/system.md\n"
        "model: m\nrepetitions: 1\noutput_dir: ./runs\n"
        "verify:\n  command: \"true\"\n"
        "conditions:\n  - {name: baseline, augmentation: null}\n"
    )


def _wait_done(client, vid, timeout=10):
    for _ in range(int(timeout * 20)):
        body = client.get(f"/api/verify/{vid}").json()
        if body["state"] in ("done", "error"):
            return body
        time.sleep(0.05)
    raise AssertionError("verify job did not finish")


def test_post_verify_runs_and_status_reaches_done(tmp_path):
    exp_dir = tmp_path / "experiments"
    _seed_experiment(exp_dir)
    client = TestClient(create_app(experiments_dir=exp_dir))
    resp = client.post("/api/verify", json={"name": "exp"})
    assert resp.status_code == 200
    vid = resp.json()["verify_id"]
    body = _wait_done(client, vid)
    assert body["state"] == "done"
    assert body["total"] == 1 and body["done"] == 1
    assert body["results"][0]["condition"] == "baseline"


def test_verify_status_404_unknown(tmp_path):
    exp_dir = tmp_path / "experiments"
    (exp_dir / "exp").mkdir(parents=True)
    client = TestClient(create_app(experiments_dir=exp_dir))
    assert client.get("/api/verify/nope").status_code == 404


def test_post_verify_404_unknown_experiment(tmp_path):
    exp_dir = tmp_path / "experiments"
    exp_dir.mkdir(parents=True)
    client = TestClient(create_app(experiments_dir=exp_dir))
    assert client.post("/api/verify", json={"name": "ghost"}).status_code == 404
