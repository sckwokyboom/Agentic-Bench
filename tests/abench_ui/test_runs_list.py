import json
from pathlib import Path

from abench_ui import runs


def test_list_runs_includes_headline_metrics(tmp_path: Path):
    d = tmp_path / "baseline" / "rep_0"
    d.mkdir(parents=True)
    (d / "metrics.json").write_text(json.dumps({
        "finished": True, "interrupted_reason": None, "verify_status": "passed",
        "success": True, "duration_s": 123.4, "n_steps": 7, "n_tool_calls": 12,
        "n_test_runs": 2, "cost": 0.0123,
    }))
    items = runs.list_runs(tmp_path)
    assert len(items) == 1
    it = items[0]
    assert it["duration_s"] == 123.4
    assert it["n_steps"] == 7
    assert it["n_tool_calls"] == 12
    assert it["n_test_runs"] == 2
    assert it["cost"] == 0.0123
