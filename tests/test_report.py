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
