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


def _seed_batched_run(root: Path, name: str, batch: str, condition: str, rep: int,
                      metrics: dict) -> None:
    """Seed <exp>/runs/<exp>/<batch>/<cond>/rep_N with metrics + trace."""
    d = root / name / "runs" / name / batch / condition / f"rep_{rep}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "metrics.json").write_text(json.dumps(metrics))
    (d / "manifest.json").write_text(json.dumps({"condition": condition, "rep": rep}))
    (d / "trace.json").write_text(json.dumps({"steps": [], "turns": [], "batch": batch}))


def test_batches_endpoint_lists_newest_first(client):
    c, root = client
    name = "exp-b"
    base = {"success": True, "interrupted_reason": None, "n_steps": 1}
    _seed_batched_run(root, name, "20260101-000000", "baseline", 0, base)
    _seed_batched_run(root, name, "20260102-000000", "baseline", 0, base)
    (root / name / "experiment.yaml").write_text("name: exp-b\nfixture_path: ./stripped\n")

    r = c.get(f"/api/runs/{name}/batches")
    assert r.status_code == 200
    ids = [b["id"] for b in r.json()]
    assert ids == ["20260102-000000", "20260101-000000"]


def test_batches_endpoint_empty(client):
    c, root = client
    (root / "exp-empty").mkdir(parents=True)
    (root / "exp-empty" / "experiment.yaml").write_text(
        "name: exp-empty\nfixture_path: ./stripped\n")
    r = c.get("/api/runs/exp-empty/batches")
    assert r.status_code == 200
    assert r.json() == []


def test_list_runs_resolves_batch(client):
    c, root = client
    name = "exp-b2"
    _seed_batched_run(root, name, "20260101-000000", "baseline", 0,
                      {"success": True, "interrupted_reason": None, "n_steps": 1})
    _seed_batched_run(root, name, "20260102-000000", "augmented", 0,
                      {"success": True, "interrupted_reason": None, "n_steps": 2})
    (root / name / "experiment.yaml").write_text("name: exp-b2\nfixture_path: ./stripped\n")

    # Default (no batch) → newest batch (2026-01-02 → augmented).
    items = c.get(f"/api/runs/{name}").json()
    assert {it["condition"] for it in items} == {"augmented"}

    # Explicit older batch → that batch's runs.
    items = c.get(f"/api/runs/{name}?batch=20260101-000000").json()
    assert {it["condition"] for it in items} == {"baseline"}

    # summary respects batch too.
    summ = c.get(f"/api/runs/{name}/summary?batch=20260101-000000").json()
    assert summ["total_runs"] == 1

    # trace artefact resolves the chosen batch's run.
    tr = c.get(f"/api/runs/{name}/baseline/0/trace?batch=20260101-000000")
    assert tr.status_code == 200
    assert tr.json()["batch"] == "20260101-000000"

    # bad batch → 404 on each.
    assert c.get(f"/api/runs/{name}?batch=nope").status_code == 404
    assert c.get(f"/api/runs/{name}/summary?batch=nope").status_code == 404
    assert c.get(f"/api/runs/{name}/baseline/0/trace?batch=nope").status_code == 404


def test_in_progress_batch_returns_empty_not_404(client):
    """A live run creates the batch dir before any rep finishes (e.g. during
    baseline verify). Polling /api/runs?batch=<that id> must return 200 [] — not
    404 — so the live page's poll doesn't flood 404s while the run is starting."""
    c, root = client
    name = "exp-ip"
    (root / name).mkdir(parents=True)
    (root / name / "experiment.yaml").write_text("name: exp-ip\nfixture_path: ./stripped\n")
    # batch dir exists, but no <cond>/rep_*/ yet (run just started)
    (root / name / "runs" / name / "20260603-135405").mkdir(parents=True)

    r = c.get(f"/api/runs/{name}?batch=20260603-135405")
    assert r.status_code == 200
    assert r.json() == []
    # genuinely-unknown batch still 404s
    assert c.get(f"/api/runs/{name}?batch=nope").status_code == 404


def test_legacy_flat_layout_still_resolves(client):
    """Existing flat-layout runs (no batch segment) must still be found via the
    newest-by-default → legacy fallback."""
    c, root = client
    _make_runs(root)  # seeds <exp-a>/runs/<exp-a>/baseline/rep_0 (FLAT)
    # list resolves
    items = c.get("/api/runs/exp-a").json()
    assert any(it["condition"] == "baseline" and it["rep"] == 0 for it in items)
    # batches surfaces a single 'legacy' batch
    batches = c.get("/api/runs/exp-a/batches").json()
    assert [b["id"] for b in batches] == ["legacy"]
    # explicit ?batch=legacy resolves too
    items = c.get("/api/runs/exp-a?batch=legacy").json()
    assert any(it["condition"] == "baseline" for it in items)
    # metrics artefact via legacy batch
    m = c.get("/api/runs/exp-a/baseline/0/metrics?batch=legacy")
    assert m.status_code == 200 and m.json()["n_steps"] == 4


def test_patch_success_batch_aware(client):
    c, root = client
    name = "exp-pb"
    _seed_batched_run(root, name, "20260101-000000", "baseline", 0,
                      {"success": None, "interrupted_reason": None})
    (root / name / "experiment.yaml").write_text("name: exp-pb\nfixture_path: ./stripped\n")
    r = c.patch(f"/api/runs/{name}/baseline/0?batch=20260101-000000",
                json={"success": True})
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_run_log_endpoint_batch_aware(client):
    """GET .../run_log returns the run.log text (200) and 404 when absent."""
    c, root = client
    name = "exp-rl"
    _seed_batched_run(root, name, "20260101-000000", "baseline", 0,
                      {"success": None, "interrupted_reason": None})
    (root / name / "experiment.yaml").write_text(
        "name: exp-rl\nfixture_path: ./stripped\n")
    rd = root / name / "runs" / name / "20260101-000000" / "baseline" / "rep_0"
    (rd / "run.log").write_text("[abench] starting task\n[abench] done\n")

    r = c.get(f"/api/runs/{name}/baseline/0/run_log?batch=20260101-000000")
    assert r.status_code == 200
    assert "[abench] starting task" in r.text

    # absent file → 404
    r = c.get(f"/api/runs/{name}/augmented/0/run_log?batch=20260101-000000")
    assert r.status_code == 404


def test_debug_log_endpoint(client):
    """The full debug.log is served on its own endpoint (with the same tail cap);
    404 when absent."""
    c, root = client
    name = "exp-dbg"
    _seed_batched_run(root, name, "20260101-000000", "baseline", 0,
                      {"success": None, "interrupted_reason": None})
    (root / name / "experiment.yaml").write_text(
        "name: exp-dbg\nfixture_path: ./stripped\n")
    rd = root / name / "runs" / name / "20260101-000000" / "baseline" / "rep_0"
    (rd / "debug.log").write_text("[opencode] verbose firehose line\n")

    r = c.get(f"/api/runs/{name}/baseline/0/debug_log?batch=20260101-000000")
    assert r.status_code == 200
    assert "verbose firehose" in r.text
    # absent → 404
    r = c.get(f"/api/runs/{name}/augmented/0/debug_log?batch=20260101-000000")
    assert r.status_code == 404


def test_run_log_tail_bytes_caps_large_log(client):
    """?tail_bytes=N returns only the END of a large log (with a notice) so the
    viewer can't freeze the browser; the full log is still available without it."""
    c, root = client
    name = "exp-rl2"
    _seed_batched_run(root, name, "20260101-000000", "baseline", 0,
                      {"success": None, "interrupted_reason": None})
    (root / name / "experiment.yaml").write_text(
        "name: exp-rl2\nfixture_path: ./stripped\n")
    rd = root / name / "runs" / name / "20260101-000000" / "baseline" / "rep_0"
    big = "\n".join(f"line-{i}" for i in range(5000)) + "\n"
    (rd / "run.log").write_text(big)

    full = c.get(f"/api/runs/{name}/baseline/0/run_log?batch=20260101-000000")
    assert full.status_code == 200
    assert "line-0\n" in full.text and "line-4999" in full.text

    tail = c.get(
        f"/api/runs/{name}/baseline/0/run_log?batch=20260101-000000&tail_bytes=200")
    assert tail.status_code == 200
    assert "run.log is large" in tail.text   # truncation notice
    assert "line-4999" in tail.text          # the END is shown
    assert "line-0\n" not in tail.text       # the head is dropped
    assert len(tail.text) < 1000             # bounded


def test_list_runs_surfaces_new_validity_fields(client):
    """list_runs items include n_service_errors / made_source_changes /
    verify_insensitive / interrupted_reason from metrics.json (defaults when
    absent)."""
    c, root = client
    name = "exp-vf"
    _seed_batched_run(root, name, "20260101-000000", "baseline", 0, {
        "success": None, "interrupted_reason": "rate_limited",
        "n_service_errors": 3, "made_source_changes": True,
        "verify_insensitive": True,
    })
    # a second run with the fields absent → defaults.
    _seed_batched_run(root, name, "20260101-000000", "augmented", 0, {
        "success": None, "interrupted_reason": None,
    })
    (root / name / "experiment.yaml").write_text(
        "name: exp-vf\nfixture_path: ./stripped\n")

    items = c.get(f"/api/runs/{name}?batch=20260101-000000").json()
    by_cond = {it["condition"]: it for it in items}

    base = by_cond["baseline"]
    assert base["n_service_errors"] == 3
    assert base["made_source_changes"] is True
    assert base["verify_insensitive"] is True
    assert base["interrupted_reason"] == "rate_limited"

    aug = by_cond["augmented"]
    assert aug["n_service_errors"] == 0
    assert aug["made_source_changes"] is False
    assert aug["verify_insensitive"] is False
    assert aug["interrupted_reason"] is None


def test_summary_tolerates_partial_run_missing_manifest(client):
    """Repro of the live-run crash: a rep interrupted before manifest.json was
    written (metrics.json present, manifest.json absent) made GET /summary 500.
    It must now return 200 and still count the partial run."""
    c, root = client
    name = "exp-partial"
    _seed_batched_run(root, name, "20260604-042657", "baseline", 0,
                      {"success": True, "interrupted_reason": None, "n_steps": 5})
    (root / name / "experiment.yaml").write_text(
        "name: exp-partial\nfixture_path: ./stripped\n")
    # rep_1: metrics.json present, manifest.json absent (aborted mid-run).
    partial = (root / name / "runs" / name / "20260604-042657"
               / "baseline" / "rep_1")
    partial.mkdir(parents=True, exist_ok=True)
    (partial / "metrics.json").write_text(json.dumps(
        {"success": None, "interrupted_reason": None, "n_steps": 7}))

    r = c.get(f"/api/runs/{name}/summary?batch=20260604-042657")
    assert r.status_code == 200
    assert r.json()["total_runs"] == 2


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
