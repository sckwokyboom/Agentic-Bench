# tests/test_runner.py
import json
from pathlib import Path

from abench.config import Condition, Experiment, MetricsCfg, OpenCodeCfg
from abench.runner import run_experiment
from tests.fakes import FakeOpenCodeClient




def _experiment(tmp_path: Path) -> Experiment:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "a.py").write_text("def f():\n    ...\n")
    reference = tmp_path / "reference"
    reference.mkdir()
    return Experiment(
        name="exp1",
        fixture_path=fixture,
        reference_path=reference,
        task_prompt="Restore f().",
        system_prompt="Be careful.",
        model="fake/model",
        output_dir=tmp_path / "runs",
        repetitions=2,
        conditions=[Condition(name="baseline", augmentation=None),
                    Condition(name="augmented", augmentation="SLICE")],
        opencode=OpenCodeCfg(),
        metrics=MetricsCfg(),
    )


def test_run_experiment_writes_all_artifacts(tmp_path):
    exp = _experiment(tmp_path)
    root = run_experiment(exp, lambda e: FakeOpenCodeClient())

    assert (root / "experiment.resolved.yaml").exists()
    for cond in ("baseline", "augmented"):
        for rep in range(2):
            rundir = root / cond / f"rep_{rep}"
            assert (rundir / "events.jsonl").read_text().strip() != ""
            assert (rundir / "trace.json").exists()
            assert (rundir / "changes.patch").exists()
            metrics = json.loads((rundir / "metrics.json").read_text())
            assert metrics["finished"] is True
            assert metrics["n_test_runs"] == 1
            assert metrics["n_files_edited"] == 1   # GENERATED.txt
            assert metrics["diff_lines_added"] >= 1
            manifest = json.loads((rundir / "manifest.json").read_text())
            assert manifest["condition"] == cond
    # augmented user_message includes the slice; baseline does not
    aug = json.loads((root / "augmented" / "rep_0" / "manifest.json").read_text())
    base = json.loads((root / "baseline" / "rep_0" / "manifest.json").read_text())
    assert "SLICE" in aug["user_message"]
    assert "SLICE" not in base["user_message"]


def test_run_experiment_writes_isolation_nonce_to_trace(tmp_path):
    """When isolation.nonce_prefix is on (default), each trace records its UUID."""
    exp = _experiment(tmp_path)  # existing helper; default isolation = both on
    run_experiment(exp, lambda e: FakeOpenCodeClient())
    root = tmp_path / "runs" / exp.name
    for cond in ("baseline", "augmented"):
        for rep in range(exp.repetitions):
            trace = json.loads((root / cond / f"rep_{rep}" / "trace.json").read_text())
            assert trace.get("isolation_nonce")  # non-empty UUID


def test_run_experiment_populates_final_diff_summary(tmp_path):
    exp = _experiment(tmp_path)
    run_experiment(exp, lambda e: FakeOpenCodeClient())
    root = tmp_path / "runs" / exp.name
    trace = json.loads((root / "baseline" / "rep_0" / "trace.json").read_text())
    fds = trace.get("final_diff_summary")
    assert fds is not None
    assert fds["total_added"] >= 1  # FakeOpenCodeClient writes GENERATED.txt
    assert any(f["path"] for f in fds["files"])
