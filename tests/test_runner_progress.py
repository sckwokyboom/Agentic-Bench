"""run_experiment emits fine-grained `progress` phase signals so the UI can
show what's happening during the otherwise-silent startup window."""
import threading
from pathlib import Path

from abench.config import (
    Condition,
    Experiment,
    IsolationCfg,
    MetricsCfg,
    OpenCodeCfg,
    VerifyCfg,
)
from abench.opencode_client import RunResult
from abench.runner import run_experiment
from abench.trace_model import Trace


def _success_result() -> RunResult:
    return RunResult(
        trace=Trace(started_at=0.0, ended_at=1.0, finished=True,
                    interrupted_reason=None),
        raw_session={"ok": True},
    )


def _rate_limited_result() -> RunResult:
    return RunResult(
        trace=Trace(started_at=0.0, ended_at=1.0, finished=False,
                    interrupted_reason="rate_limit", n_service_errors=1,
                    n_rate_limits=1),
        raw_session=None,
    )


class _SequenceClient:
    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    def run_task(self, *, workdir, system_prompt, model, user_message,
                 timeout_s, on_event, log_sink=None, cancel_event=None):
        self.calls += 1
        on_event({"type": "message.start", "attempt": self.calls})
        idx = min(self.calls - 1, len(self._results) - 1)
        return self._results[idx]


def _experiment(tmp_path: Path, *, retries: int = 0,
                verify: bool = False) -> Experiment:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "a.py").write_text("x = 1\n")
    reference = tmp_path / "reference"
    reference.mkdir()
    (reference / "a.py").write_text("x = 2\n")
    return Experiment(
        name="progress-exp",
        fixture_path=fixture,
        reference_path=reference,
        task_prompt="t",
        system_prompt="s",
        model="fake/model",
        output_dir=tmp_path / "runs",
        repetitions=1,
        conditions=[Condition(name="baseline", augmentation=None)],
        opencode=OpenCodeCfg(),
        metrics=MetricsCfg(),
        isolation=IsolationCfg(nonce_prefix=False, shuffle_order=False),
        verify=VerifyCfg(enabled=verify),
        rate_limit_retries=retries,
        rate_limit_backoff_s=0.0,
    )


def _collect(exp, client, **kw) -> list[dict]:
    phases: list[dict] = []
    run_experiment(exp, lambda e: client, batch_id="20260601-000000",
                   progress=phases.append, **kw)
    return phases


def test_preparing_workdir_emitted_per_run(tmp_path):
    """A normal run emits a preparing_workdir phase carrying the run position."""
    exp = _experiment(tmp_path)
    phases = _collect(exp, _SequenceClient([_success_result()]))

    prep = [p for p in phases if p["phase"] == "preparing_workdir"]
    assert len(prep) == 1
    assert prep[0]["run_idx"] == 1
    assert prep[0]["condition"] == "baseline"
    assert prep[0]["rep"] == 0
    assert prep[0]["message"]  # non-empty human-readable text


def test_baseline_verify_phase_emitted_when_verify_enabled(tmp_path):
    """With verify enabled the baseline pre-flight phase is announced before the
    (silent, possibly multi-minute) baseline verification runs."""
    exp = _experiment(tmp_path, verify=True)
    phases = _collect(exp, _SequenceClient([_success_result()]))

    kinds = [p["phase"] for p in phases]
    assert "baseline_verify" in kinds
    # Baseline verify is a session-level phase, announced before the first run.
    assert kinds.index("baseline_verify") < kinds.index("preparing_workdir")


def test_no_baseline_verify_phase_when_disabled(tmp_path):
    exp = _experiment(tmp_path, verify=False)
    phases = _collect(exp, _SequenceClient([_success_result()]))
    assert all(p["phase"] != "baseline_verify" for p in phases)


def test_rate_limit_backoff_phase_emitted_on_retry(tmp_path):
    """A 429 that triggers a retry emits a rate_limit_backoff phase with the
    retry counter and backoff seconds for the UI countdown."""
    exp = _experiment(tmp_path, retries=1)
    phases = _collect(exp, _SequenceClient([_rate_limited_result(),
                                            _success_result()]))

    backoff = [p for p in phases if p["phase"] == "rate_limit_backoff"]
    assert len(backoff) == 1
    assert backoff[0]["retry"] == 1
    assert backoff[0]["max_retries"] == 1
    assert backoff[0]["backoff_s"] == 0.0


def test_progress_is_optional(tmp_path):
    """Omitting progress (the CLI path) must not raise."""
    exp = _experiment(tmp_path)
    client = _SequenceClient([_success_result()])
    # No progress= kwarg at all.
    run_experiment(exp, lambda e: client, batch_id="20260601-000000")
    assert client.calls == 1


def test_cancel_still_works_with_progress(tmp_path):
    """Smoke: progress threading doesn't disturb cancel handling."""
    exp = _experiment(tmp_path)
    cancel = threading.Event()
    cancel.set()  # cancel before any run
    phases = _collect(exp, _SequenceClient([_success_result()]),
                      cancel_event=cancel)
    # Cancelled before the loop body → no preparing_workdir phase.
    assert all(p["phase"] != "preparing_workdir" for p in phases)
