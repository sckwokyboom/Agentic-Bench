# tests/test_report.py
import json
from pathlib import Path

from abench.report import load_runs, write_report


def _write_run(root: Path, cond: str, rep: int, n_steps: int,
               interrupted=None) -> None:
    rundir = root / cond / f"rep_{rep}"
    rundir.mkdir(parents=True)
    (rundir / "manifest.json").write_text(json.dumps({"condition": cond, "rep": rep}))
    (rundir / "metrics.json").write_text(json.dumps({
        "duration_s": 10.0, "n_steps": n_steps, "n_tool_calls": 5,
        "n_test_runs": 2, "n_reads": 3, "n_searches": 1,
        "n_files_edited": 1, "diff_lines_added": 4, "diff_lines_removed": 0,
        "tokens_in": 100, "tokens_out": 200, "cost": None,
        "time_to_first_edit_s": 2.0, "finished": True,
        "interrupted_reason": interrupted, "success": None,
    }))


def test_load_and_report(tmp_path):
    root = tmp_path / "runs" / "exp1"
    _write_run(root, "baseline", 0, n_steps=10)
    _write_run(root, "baseline", 1, n_steps=12)
    _write_run(root, "augmented", 0, n_steps=6)
    _write_run(root, "augmented", 1, n_steps=8)
    _write_run(root, "augmented", 2, n_steps=99, interrupted="rate_limit")

    df = load_runs(root)
    assert len(df) == 5

    write_report(root)
    assert (root / "summary.csv").exists()
    md = (root / "summary.md").read_text()
    assert "## Mean per condition" in md
    # invalid (rate_limit) run excluded -> augmented mean n_steps == 7, not pulled to ~37
    assert "n_steps" in md


from abench import report


def _write_summary_run(root: Path, condition: str, rep: int, metrics: dict) -> None:
    d = root / condition / f"rep_{rep}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "metrics.json").write_text(json.dumps(metrics))
    (d / "manifest.json").write_text(json.dumps({"condition": condition, "rep": rep}))


def test_summary_json_means_and_deltas(tmp_path: Path):
    root = tmp_path / "runs"
    base = {"interrupted_reason": None, "success": True}
    _write_summary_run(root, "baseline", 0, {**base, "n_steps": 10, "duration_s": 100.0, "cost": 0.02})
    _write_summary_run(root, "baseline", 1, {**base, "n_steps": 20, "duration_s": 200.0, "cost": 0.04})
    _write_summary_run(root, "augmented", 0, {**base, "n_steps": 6, "duration_s": 80.0, "cost": 0.03})
    _write_summary_run(root, "augmented", 1, {**base, "n_steps": 6, "duration_s": 120.0, "cost": 0.03})

    out = report.summary_json(root)

    assert out["total_runs"] == 4
    assert out["valid_runs"] == 4
    conds = {c["name"]: c for c in out["conditions"]}
    assert conds["baseline"]["metrics"]["n_steps"]["mean"] == 15.0
    assert conds["augmented"]["metrics"]["n_steps"]["mean"] == 6.0
    assert conds["baseline"]["success_rate"] == 1.0
    assert out["deltas"]["n_steps"] == -60.0


def test_summary_json_excludes_interrupted_and_handles_empty(tmp_path: Path):
    root = tmp_path / "runs"
    _write_summary_run(root, "baseline", 0, {"interrupted_reason": "timeout", "success": None, "n_steps": 99})
    out = report.summary_json(root)
    assert out["total_runs"] == 1
    assert out["valid_runs"] == 0
    assert out["conditions"] == []
    assert out["deltas"] == {}

    empty = report.summary_json(tmp_path / "nope")
    assert empty == {"conditions": [], "deltas": {}, "total_runs": 0, "valid_runs": 0}


def test_load_runs_tolerates_missing_manifest(tmp_path: Path):
    """A run interrupted before manifest.json was written (metrics.json present,
    manifest.json absent — it's the last artefact _run_one writes) must not
    crash; condition + rep are recovered from the on-disk path."""
    root = tmp_path / "runs"
    _write_summary_run(root, "baseline", 0,
                       {"interrupted_reason": None, "success": True, "n_steps": 10})
    partial = root / "baseline" / "rep_1"
    partial.mkdir(parents=True)
    (partial / "metrics.json").write_text(json.dumps(
        {"interrupted_reason": None, "success": None, "n_steps": 12}))

    df = load_runs(root)
    assert len(df) == 2
    assert sorted(int(r) for r in df["rep"]) == [0, 1]
    assert set(df["condition"]) == {"baseline"}

    out = report.summary_json(root)  # must not raise
    assert out["total_runs"] == 2


def test_load_runs_skips_unreadable_metrics(tmp_path: Path):
    """A truncated/half-written metrics.json is skipped, not fatal."""
    root = tmp_path / "runs"
    _write_summary_run(root, "baseline", 0,
                       {"interrupted_reason": None, "success": True, "n_steps": 10})
    broken = root / "baseline" / "rep_1"
    broken.mkdir(parents=True)
    (broken / "metrics.json").write_text("{not valid json")

    df = load_runs(root)
    assert len(df) == 1
    assert report.summary_json(root)["total_runs"] == 1
