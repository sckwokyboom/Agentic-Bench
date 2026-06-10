# tests/test_runner.py
import json
import threading
from pathlib import Path
from typing import Callable

from abench.config import Condition, Experiment, MetricsCfg, OpenCodeCfg
from abench.opencode_client import RunResult
from abench.runner import run_experiment
from abench.trace_model import Trace
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
                 timeout_s, on_event, log_sink=None, debug_sink=None, cancel_event=None):
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


def test_run_writes_both_readable_and_debug_logs(tmp_path):
    """Each run writes run.log (readable) and debug.log (full); the readable log
    carries the agent's concise line and both carry the header."""
    exp = _experiment(tmp_path)
    root = run_experiment(exp, lambda e: FakeOpenCodeClient())
    rundir = root / "baseline" / "rep_0"
    run_log = rundir / "run.log"
    debug_log = rundir / "debug.log"
    assert run_log.is_file() and debug_log.is_file()
    assert "[fake] starting task" in run_log.read_text()
    assert "# condition: baseline" in run_log.read_text()
    assert "# condition: baseline" in debug_log.read_text()


class _CancelAfterFirstClient(FakeOpenCodeClient):
    """Fake client that sets a cancel_event after its first run_task call, so
    the runner's pre-run cancel check breaks the loop before the second run."""

    def __init__(self, cancel_event: threading.Event):
        self._cancel_event = cancel_event
        self._calls = 0

    def run_task(self, *, workdir, system_prompt, model, user_message,
                 timeout_s, on_event, log_sink=None, debug_sink=None, cancel_event=None):
        self._calls += 1
        result = super().run_task(
            workdir=workdir, system_prompt=system_prompt, model=model,
            user_message=user_message, timeout_s=timeout_s,
            on_event=on_event, log_sink=log_sink,
        )
        # Trip the cancel flag after the first run completes.
        self._cancel_event.set()
        return result


def test_run_experiment_breaks_loop_on_cancel(tmp_path):
    """With a 2-run plan, cancelling after the first run must stop the loop so
    the second run's dir is never created."""
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "a.py").write_text("def f():\n    ...\n")
    reference = tmp_path / "reference"
    reference.mkdir()
    exp = Experiment(
        name="cancel-exp",
        fixture_path=fixture,
        reference_path=reference,
        task_prompt="t", system_prompt="s", model="fake/model",
        output_dir=tmp_path / "runs",
        repetitions=2,
        conditions=[Condition(name="baseline", augmentation=None)],
        opencode=OpenCodeCfg(),
        metrics=MetricsCfg(),
    )
    # Disable shuffle so the plan order (rep_0 then rep_1) is deterministic.
    exp.isolation.shuffle_order = False
    cancel_event = threading.Event()
    root = run_experiment(
        exp,
        lambda e: _CancelAfterFirstClient(cancel_event),
        batch_id="20260601-000000",
        cancel_event=cancel_event,
    )
    assert (root / "baseline" / "rep_0").is_dir()
    # The second run must have been skipped — its dir is never created.
    assert not (root / "baseline" / "rep_1").exists()


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


def test_run_experiment_overlay_rendered_in_workdir(tmp_path, monkeypatch):
    """overlay_env {env:NAME} is expanded and *.tmpl is rendered into the workdir
    the fake client receives — asserts end-to-end wiring from run_experiment.

    The workdir is cleaned up after the run, so we read the rendered file *inside*
    run_task (while the workdir is still alive) and store the content for later
    assertion.
    """
    # Build a small overlay directory with one .tmpl file.
    overlay = tmp_path / "overlay"
    overlay.mkdir()
    (overlay / "tool_config.txt.tmpl").write_text("endpoint=${TOOL_ENDPOINT}\n")

    # Fixture source dir.
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "a.py").write_text("x = 1\n")

    reference = tmp_path / "reference"
    reference.mkdir()

    monkeypatch.setenv("TOOL_ENDPOINT", "http://localhost:9999")

    captured: dict = {}

    class _CapturingClient:
        """Reads the rendered overlay file from the live workdir during run_task."""

        def run_task(self, *, workdir: str, system_prompt: str, model: str,
                     user_message: str, timeout_s: int,
                     on_event: Callable[[dict], None],
                     log_sink: Callable[[str], None] | None = None,
                     debug_sink: Callable[[str], None] | None = None,
                     cancel_event=None) -> RunResult:
            rendered = Path(workdir) / "tool_config.txt"
            captured["exists"] = rendered.exists()
            if captured["exists"]:
                captured["content"] = rendered.read_text()
            on_event({"type": "message.start"})
            trace = Trace(started_at=0.0, ended_at=1.0, finished=True)
            return RunResult(trace=trace, raw_session=None)

    exp = Experiment(
        name="overlay-exp",
        fixture_path=fixture,
        reference_path=reference,
        task_prompt="Do nothing.",
        system_prompt="s",
        model="fake/model",
        output_dir=tmp_path / "runs",
        repetitions=1,
        conditions=[Condition(name="with-overlay", augmentation=None,
                              overlay=str(overlay))],
        opencode=OpenCodeCfg(),
        metrics=MetricsCfg(),
        overlay_env={"TOOL_ENDPOINT": "{env:TOOL_ENDPOINT}"},
    )
    run_experiment(exp, lambda e: _CapturingClient())

    assert captured.get("exists"), "rendered overlay file must exist in workdir"
    assert captured["content"] == "endpoint=http://localhost:9999\n"
