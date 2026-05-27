# tests/test_cli.py
import json
from pathlib import Path

from abench.cli import main


def _write_run(root: Path, cond: str, rep: int) -> None:
    rundir = root / cond / f"rep_{rep}"
    rundir.mkdir(parents=True)
    (rundir / "manifest.json").write_text(json.dumps({"condition": cond, "rep": rep}))
    (rundir / "metrics.json").write_text(json.dumps({
        "duration_s": 1.0, "n_steps": 3, "n_tool_calls": 1, "n_test_runs": 0,
        "n_reads": 0, "n_searches": 0, "n_files_edited": 1,
        "diff_lines_added": 1, "diff_lines_removed": 0, "tokens_in": None,
        "tokens_out": None, "cost": None, "time_to_first_edit_s": None,
        "finished": True, "interrupted_reason": None, "success": None,
    }))


def test_cli_report_writes_summary(tmp_path):
    root = tmp_path / "runs" / "exp1"
    _write_run(root, "baseline", 0)
    rc = main(["report", str(root)])
    assert rc == 0
    assert (root / "summary.csv").exists()
    assert (root / "summary.md").exists()
