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


class _ServiceErrorClient:
    """Fake client whose returned trace carries service errors counted from
    raw events (429 + 503), and writes a line through log_sink."""

    def run_task(self, *, workdir, system_prompt, model, user_message,
                 timeout_s, on_event, log_sink=None):
        from abench.opencode_client import _count_service_errors
        from abench.opencode_client import RunResult
        from abench.trace_model import Trace
        raw_events = [
            {"type": "error", "error": {"statusCode": 429, "message": "rate limited"}},
            {"type": "error", "error": {"statusCode": 503, "message": "unavailable"}},
        ]
        if log_sink is not None:
            log_sink("[fake] simulated service errors")
        n_err, n_rl, msgs = _count_service_errors(raw_events)
        trace = Trace(started_at=0.0, ended_at=1.0, finished=False,
                      interrupted_reason="rate_limit",
                      n_service_errors=n_err, n_rate_limits=n_rl,
                      service_error_messages=msgs)
        return RunResult(trace=trace, raw_session=None)


def test_run_one_propagates_service_error_counters(tmp_path):
    exp = _experiment(tmp_path)
    root = run_experiment(exp, lambda e: _ServiceErrorClient())
    rundir = root / "baseline" / "rep_0"
    trace = json.loads((rundir / "trace.json").read_text())
    assert trace["n_service_errors"] >= 2
    assert trace["n_rate_limits"] == 1
    metrics = json.loads((rundir / "metrics.json").read_text())
    assert metrics["n_service_errors"] >= 2
    assert metrics["n_rate_limits"] == 1
    # This client makes no source edits → made_source_changes False
    assert metrics["made_source_changes"] is False
    # run.log captured the sink line
    assert "simulated service errors" in (rundir / "run.log").read_text()


def test_run_one_writes_run_log_and_error_metrics(tmp_path):
    exp = _experiment(tmp_path)
    root = run_experiment(exp, lambda e: FakeOpenCodeClient())
    rundir = root / "baseline" / "rep_0"
    # run.log written and non-empty (header + at least the fake's line)
    log = (rundir / "run.log").read_text()
    assert log.strip() != ""
    assert "# condition: baseline" in log
    assert "# model: fake/model" in log
    # metrics carry the new counters + boolean
    metrics = json.loads((rundir / "metrics.json").read_text())
    assert metrics["n_service_errors"] == 0
    assert metrics["n_rate_limits"] == 0
    # FakeOpenCodeClient writes GENERATED.txt → real source change
    assert metrics["made_source_changes"] is True


def test_run_experiment_writes_isolation_nonce_to_trace(tmp_path):
    """When isolation.nonce_prefix is on (default), each trace records its UUID."""
    exp = _experiment(tmp_path)  # existing helper; default isolation = both on
    root = run_experiment(exp, lambda e: FakeOpenCodeClient())
    for cond in ("baseline", "augmented"):
        for rep in range(exp.repetitions):
            trace = json.loads((root / cond / f"rep_{rep}" / "trace.json").read_text())
            assert trace.get("isolation_nonce")  # non-empty UUID


def test_run_experiment_populates_final_diff_summary(tmp_path):
    exp = _experiment(tmp_path)
    root = run_experiment(exp, lambda e: FakeOpenCodeClient())
    trace = json.loads((root / "baseline" / "rep_0" / "trace.json").read_text())
    fds = trace.get("final_diff_summary")
    assert fds is not None
    assert fds["total_added"] >= 1  # FakeOpenCodeClient writes GENERATED.txt
    assert any(f["path"] for f in fds["files"])
