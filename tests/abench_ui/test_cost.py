"""Total $ spend across every run of every experiment (sum of each run's
metrics.json `cost`, all batches incl. the legacy flat layout)."""
import json
from pathlib import Path

from abench_ui.runs import cost_summary


def _run(root: Path, exp: str, sub: str, cond: str, rep: int, cost):
    d = root / exp / "runs" / exp / sub / cond / f"rep_{rep}"
    d.mkdir(parents=True)
    (d / "metrics.json").write_text(json.dumps({"cost": cost}))


def test_cost_summary_sums_all_runs_across_experiments_and_batches(tmp_path):
    _run(tmp_path, "exp-a", "20260101-000000", "baseline", 0, 0.01)
    _run(tmp_path, "exp-a", "20260101-000000", "augmented", 0, 0.02)
    _run(tmp_path, "exp-a", "20260102-000000", "baseline", 0, 0.03)  # a 2nd batch
    _run(tmp_path, "exp-b", "20260101-000000", "baseline", 0, 0.10)
    _run(tmp_path, "exp-b", "20260101-000000", "augmented", 0, None)  # free / no cost

    s = cost_summary(tmp_path)
    assert s["total_cost"] == 0.16          # 0.01+0.02+0.03+0.10
    assert s["n_runs"] == 5
    assert s["n_runs_with_cost"] == 4       # the None-cost run is counted but unpriced
    assert s["by_experiment"]["exp-a"] == 0.06
    assert s["by_experiment"]["exp-b"] == 0.10


def test_cost_summary_handles_legacy_flat_layout(tmp_path):
    # legacy: <exp>/runs/<exp>/<cond>/rep_N (no batch dir between)
    d = tmp_path / "exp-c" / "runs" / "exp-c" / "baseline" / "rep_0"
    d.mkdir(parents=True)
    (d / "metrics.json").write_text(json.dumps({"cost": 0.05}))
    s = cost_summary(tmp_path)
    assert s["total_cost"] == 0.05 and s["n_runs"] == 1


def test_cost_summary_empty(tmp_path):
    assert cost_summary(tmp_path) == {
        "total_cost": 0.0, "n_runs": 0, "n_runs_with_cost": 0, "by_experiment": {},
    }


def test_cost_endpoint(tmp_path):
    from fastapi.testclient import TestClient
    from abench_ui.server import create_app
    _run(tmp_path, "exp-a", "20260101-000000", "baseline", 0, 0.07)
    c = TestClient(create_app(experiments_dir=tmp_path))
    r = c.get("/api/cost")
    assert r.status_code == 200
    assert r.json()["total_cost"] == 0.07 and r.json()["n_runs"] == 1
