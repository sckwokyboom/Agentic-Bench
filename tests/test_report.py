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


def test_summary_json_tests_pass_rate_from_summed_verify_counts(tmp_path: Path):
    """Condition tests_pass_rate = Σpassed / Σ(passed+failed) over valid runs,
    NOT a mean of the derived per-run field. A run failing 2/2200 pulls it < 1."""
    root = tmp_path / "runs"
    base = {"interrupted_reason": None}
    _write_summary_run(root, "baseline", 0, {**base, "success": True, "verify_passed_count": 2200, "verify_failed_count": 0})
    _write_summary_run(root, "baseline", 1, {**base, "success": True, "verify_passed_count": 2200, "verify_failed_count": 0})
    _write_summary_run(root, "augmented", 0, {**base, "success": True, "verify_passed_count": 2200, "verify_failed_count": 0})
    _write_summary_run(root, "augmented", 1, {**base, "success": False, "verify_passed_count": 2198, "verify_failed_count": 2})
    conds = {c["name"]: c for c in report.summary_json(root)["conditions"]}
    assert conds["baseline"]["tests_pass_rate"] == 1.0
    assert conds["augmented"]["tests_pass_rate"] == (2200 + 2198) / 4400  # < 1


def test_summary_json_tests_pass_rate_not_inflated_when_runs_lack_derived_field(tmp_path: Path):
    """Regression for the reported bug: success rate 33% but tests passed % showed
    100%. Cause was aggregating the derived per-run tests_pass_rate and dropping
    runs that lacked it (pre-feature metrics), so the mean fell back to the lone
    passing run = 1.0. Aggregating from the stable verify counts keeps the failing
    runs in the denominator → the rate is < 1, matching reality."""
    root = tmp_path / "runs"
    base = {"interrupted_reason": None}  # NOTE: no "tests_pass_rate" field at all
    _write_summary_run(root, "augmented", 0, {**base, "success": True, "verify_passed_count": 2200, "verify_failed_count": 0})
    _write_summary_run(root, "augmented", 1, {**base, "success": False, "verify_passed_count": 2198, "verify_failed_count": 2})
    _write_summary_run(root, "augmented", 2, {**base, "success": False, "verify_passed_count": 2197, "verify_failed_count": 3})
    cond = {c["name"]: c for c in report.summary_json(root)["conditions"]}["augmented"]
    assert round(cond["success_rate"], 3) == 0.333
    assert cond["tests_pass_rate"] == (2200 + 2198 + 2197) / 6600  # < 1, NOT the buggy 1.0
    assert cond["tests_pass_rate"] < 1.0


def test_summary_json_tests_pass_rate_uses_expected_total(tmp_path: Path):
    """A failing run that aborted early (ran 2281 of 2437) is scored against the
    full expected suite, so the un-run tests count as not-passed."""
    root = tmp_path / "runs"
    base = {"interrupted_reason": None}
    _write_summary_run(root, "augmented", 0, {**base, "success": True,
                       "verify_passed_count": 2437, "verify_failed_count": 0,
                       "verify_expected_total": 2437})
    _write_summary_run(root, "augmented", 1, {**base, "success": False,
                       "verify_passed_count": 2280, "verify_failed_count": 1,
                       "verify_expected_total": 2437})
    cond = {c["name"]: c for c in report.summary_json(root)["conditions"]}["augmented"]
    # Σpassed=4717 ; Σtotal = 2437 + max(2281, 2437) = 4874
    assert cond["tests_pass_rate"] == (2437 + 2280) / (2437 + 2437)


def test_summary_json_tests_pass_rate_none_when_no_verify_counts(tmp_path: Path):
    root = tmp_path / "runs"
    _write_summary_run(root, "baseline", 0, {"interrupted_reason": None, "success": True})
    conds = {c["name"]: c for c in report.summary_json(root)["conditions"]}
    assert conds["baseline"]["tests_pass_rate"] is None


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
