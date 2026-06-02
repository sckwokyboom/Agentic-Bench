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


def _seed_batched_experiment(exp_dir: Path, batch: str):
    """Seed an experiment whose run lives under a TIMESTAMPED batch dir:
    <exp>/runs/exp/<batch>/baseline/rep_0/."""
    d = exp_dir / "exp"
    (d / "fix").mkdir(parents=True)
    (d / "fix" / "a.txt").write_text("old\n")
    rd = d / "runs" / "exp" / batch / "baseline" / "rep_0"
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
    return rd


def _seed_extra_batch_run(exp_dir: Path, batch: str):
    """Add a baseline/rep_0 run under another batch dir of an already-seeded
    experiment (does not touch experiment.yaml)."""
    rd = exp_dir / "exp" / "runs" / "exp" / batch / "baseline" / "rep_0"
    rd.mkdir(parents=True)
    patch = ("diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n")
    (rd / "changes.patch").write_text(patch)
    (rd / "metrics.json").write_text(json.dumps({"verify_status": "error", "success": None}))
    (rd / "trace.json").write_text(json.dumps({"steps": [], "turns": []}))
    return rd


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


def test_per_run_failure_lands_as_result_row_not_job_crash(tmp_path):
    """A run whose changes.patch won't apply must surface as an error result row;
    the job itself must still reach state=done (not crash to state=error)."""
    exp_dir = tmp_path / "experiments"
    _seed_experiment(exp_dir)
    # Replace the good patch with an unapplyable one.
    bogus = exp_dir / "exp" / "runs" / "exp" / "baseline" / "rep_0" / "changes.patch"
    bogus.write_text("diff --git a/a.txt b/a.txt\n@@ bogus @@\nnonsense\n")
    client = TestClient(create_app(experiments_dir=exp_dir))
    vid = client.post("/api/verify", json={"name": "exp"}).json()["verify_id"]
    body = _wait_done(client, vid)
    assert body["state"] == "done"
    assert body["done"] == 1
    assert body["results"][0]["reason"] == "patch_apply_failed"
    assert body["results"][0]["status"] == "error"


def test_post_verify_batch_reverifies_that_batch(tmp_path):
    """A POST /api/verify {name, batch} against a TIMESTAMPED-BATCH layout must
    discover and re-verify THAT batch's runs (not silently 0, and not the
    newest batch by default). Two batches are seeded and the OLDER one is
    targeted, so a non-batch-aware handler would write back to the wrong dir."""
    exp_dir = tmp_path / "experiments"
    older = "20260101-000000"
    newer = "20260202-000000"
    older_rd = _seed_batched_experiment(exp_dir, older)
    newer_rd = _seed_extra_batch_run(exp_dir, newer)
    client = TestClient(create_app(experiments_dir=exp_dir))
    resp = client.post("/api/verify", json={"name": "exp", "batch": older})
    assert resp.status_code == 200
    vid = resp.json()["verify_id"]
    body = _wait_done(client, vid)
    assert body["state"] == "done"
    assert body["total"] == 1 and body["done"] == 1
    assert body["results"][0]["condition"] == "baseline"
    # The run actually ran (not silently no-op'd): result row carries a real
    # verify reason, not the "no_run" sentinel.
    assert body["results"][0]["reason"] != "no_run"
    # The TARGETED (older) batch was written back in place …
    older_m = json.loads((older_rd / "metrics.json").read_text())
    assert "verify_reason" in older_m
    assert (older_rd / "verify_output.log").is_file()
    # … and the newer batch was left untouched.
    newer_m = json.loads((newer_rd / "metrics.json").read_text())
    assert "verify_reason" not in newer_m
    assert not (newer_rd / "verify_output.log").exists()


def test_post_verify_default_batch_finds_newest(tmp_path):
    """No batch in the body → newest batch is discovered (total > 0)."""
    exp_dir = tmp_path / "experiments"
    _seed_batched_experiment(exp_dir, "20260101-000000")
    client = TestClient(create_app(experiments_dir=exp_dir))
    vid = client.post("/api/verify", json={"name": "exp"}).json()["verify_id"]
    body = _wait_done(client, vid)
    assert body["state"] == "done"
    assert body["total"] == 1 and body["done"] == 1


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
