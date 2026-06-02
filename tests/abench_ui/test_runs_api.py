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


def test_realshape_trace_and_metrics_flow_through_endpoints(client):
    """End-to-end contract smoke (plan Task 10 Step 3): a finished run whose
    trace.json carries the REAL normalized shape (a tool_call paired with its
    tool_result + a file_edit) and whose metrics.json has non-zero
    reads/tests-executed/cache must survive the endpoints intact, so the
    frontend trace model renders real tools/edits and non-zero aggregates
    (the old all-zero bug)."""
    c, root = client
    name = "exp-rs"
    rd = root / name / "runs" / name / "baseline" / "rep_0"
    rd.mkdir(parents=True)
    (rd / "manifest.json").write_text(json.dumps({"condition": "baseline", "rep": 0}))
    (root / name / "experiment.yaml").write_text("name: exp-rs\nfixture_path: ./stripped\n")
    (rd / "trace.json").write_text(json.dumps({
        "steps": [
            {"kind": "reasoning", "ts": 1.0, "turn": 0, "message_id": "M0", "text": "look first"},
            {"kind": "tool_call", "ts": 2.0, "turn": 0, "message_id": "M0",
             "tool_name": "read", "tool_args": {"path": "a.py"}, "tool_call_id": "c1"},
            {"kind": "tool_result", "ts": 3.0, "turn": 0, "message_id": "M0",
             "tool_call_id": "c1", "output": "file body", "exit_code": 0},
            {"kind": "file_edit", "ts": 4.0, "turn": 0, "message_id": "M0",
             "path": "a.py", "patch": "@@\n-x\n+y\n"},
        ],
        "turns": [
            {"message_id": "M0", "reason": "tool-calls", "tokens_in": 100,
             "tokens_out": 20, "tokens_reasoning": 5, "cost": 0.001,
             "started_at": 1.0, "ended_at": 4.0},
        ],
    }))
    (rd / "metrics.json").write_text(json.dumps({
        "finished": True, "interrupted_reason": None, "success": None,
        "verify_status": "passed",
        "n_steps": 1, "n_tool_calls": 1, "n_reads": 3, "n_searches": 2,
        "n_test_runs": 1, "n_tests_executed": 7,
        "tokens_in": 11700, "tokens_out": 118, "tokens_reasoning": 5,
        "cache_read": 0, "cache_write": 0, "cost": 0.0017,
    }))

    # trace endpoint preserves the discriminating real-shape fields the UI needs
    tr = c.get(f"/api/runs/{name}/baseline/0/trace").json()
    kinds = [s["kind"] for s in tr["steps"]]
    assert kinds == ["reasoning", "tool_call", "tool_result", "file_edit"]
    tool_call = next(s for s in tr["steps"] if s["kind"] == "tool_call")
    tool_result = next(s for s in tr["steps"] if s["kind"] == "tool_result")
    assert tool_call["tool_name"] == "read" and tool_call["tool_call_id"] == "c1"
    assert tool_result["tool_call_id"] == "c1" and tool_result["exit_code"] == 0
    assert any(s["kind"] == "file_edit" and s["path"] == "a.py" for s in tr["steps"])
    assert tr["turns"][0]["message_id"] == "M0" and tr["turns"][0]["tokens_in"] == 100

    # metrics endpoint surfaces the non-zero counts the aggregate bar reads
    m = c.get(f"/api/runs/{name}/baseline/0/metrics").json()
    assert m["n_reads"] == 3 and m["n_searches"] == 2
    assert m["n_test_runs"] == 1 and m["n_tests_executed"] == 7
    assert m["tokens_in"] == 11700 and m["tokens_out"] == 118
    assert "cache_read" in m and "cost" in m
