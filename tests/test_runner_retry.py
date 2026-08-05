# tests/test_runner_retry.py
import json
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


def _rate_limited_result() -> RunResult:
    return RunResult(
        trace=Trace(
            started_at=0.0,
            ended_at=1.0,
            finished=False,
            interrupted_reason="rate_limit",
            n_service_errors=1,
            n_rate_limits=1,
        ),
        raw_session=None,
    )


def _success_result() -> RunResult:
    return RunResult(
        trace=Trace(
            started_at=0.0,
            ended_at=1.0,
            finished=True,
            interrupted_reason=None,
        ),
        raw_session={"ok": True},
    )


class _SequenceClient:
    """Fake client returning a configurable SEQUENCE of RunResults.

    Tracks the number of run_task calls. If the sequence is exhausted, the
    last result is repeated. Optionally sets a cancel_event after the first
    call to simulate a user cancel mid-retry.
    """

    def __init__(self, results, *, set_cancel: threading.Event | None = None):
        self._results = list(results)
        self.calls = 0
        self._set_cancel = set_cancel

    def run_task(self, *, workdir, system_prompt, model, user_message,
                 timeout_s, agent_tools=None, on_event, log_sink=None, debug_sink=None, cancel_event=None,
                 temperature=None):
        self.calls += 1
        on_event({"type": "message.start", "attempt": self.calls})
        if log_sink is not None:
            log_sink(f"[fake] attempt {self.calls}")
        idx = min(self.calls - 1, len(self._results) - 1)
        result = self._results[idx]
        if self._set_cancel is not None:
            self._set_cancel.set()
        return result


def _experiment(tmp_path: Path, *, retries: int) -> Experiment:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "a.py").write_text("x = 1\n")
    reference = tmp_path / "reference"
    reference.mkdir()
    return Experiment(
        name="retry-exp",
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
        # Deterministic + instant + single-attempt-friendly:
        isolation=IsolationCfg(nonce_prefix=False, shuffle_order=False),
        verify=VerifyCfg(enabled=False),
        rate_limit_retries=retries,
        rate_limit_backoff_s=0.0,
    )


def test_retry_then_succeed(tmp_path):
    """429 on attempt 1, success on attempt 2 → client called exactly twice,
    final metrics reflect the successful (non-rate-limited) run."""
    exp = _experiment(tmp_path, retries=3)
    client = _SequenceClient([_rate_limited_result(), _success_result()])
    root = run_experiment(exp, lambda e: client, batch_id="20260601-000000")

    assert client.calls == 2
    rundir = root / "baseline" / "rep_0"
    metrics = json.loads((rundir / "metrics.json").read_text())
    assert metrics["interrupted_reason"] is None
    assert metrics["finished"] is True
    assert (rundir / "manifest.json").is_file()


def test_retries_exhausted(tmp_path):
    """Always 429 with retries=2 → 1 initial + 2 retries = 3 calls; the final
    recorded run is still rate-limited and artifacts are written."""
    exp = _experiment(tmp_path, retries=2)
    client = _SequenceClient([_rate_limited_result()])
    root = run_experiment(exp, lambda e: client, batch_id="20260601-000000")

    assert client.calls == 3
    rundir = root / "baseline" / "rep_0"
    metrics = json.loads((rundir / "metrics.json").read_text())
    assert metrics["interrupted_reason"] == "rate_limit"
    assert (rundir / "manifest.json").is_file()
    assert (rundir / "metrics.json").is_file()


def test_disabled_does_not_retry(tmp_path):
    """retries=0 → single attempt even when rate-limited."""
    exp = _experiment(tmp_path, retries=0)
    client = _SequenceClient([_rate_limited_result()])
    root = run_experiment(exp, lambda e: client, batch_id="20260601-000000")

    assert client.calls == 1
    rundir = root / "baseline" / "rep_0"
    metrics = json.loads((rundir / "metrics.json").read_text())
    assert metrics["interrupted_reason"] == "rate_limit"


def test_cancel_aborts_retry(tmp_path):
    """A cancel_event tripped during the first run must stop retrying; with
    retries=5 and the event set after attempt 1, attempts stay at 1."""
    exp = _experiment(tmp_path, retries=5)
    cancel_event = threading.Event()
    client = _SequenceClient([_rate_limited_result()], set_cancel=cancel_event)
    root = run_experiment(
        exp,
        lambda e: client,
        batch_id="20260601-000000",
        cancel_event=cancel_event,
    )

    assert client.calls == 1
    rundir = root / "baseline" / "rep_0"
    # The (single, rate-limited) run is still recorded.
    metrics = json.loads((rundir / "metrics.json").read_text())
    assert metrics["interrupted_reason"] == "rate_limit"


def _stillborn_result() -> RunResult:
    """A 407 before the first turn: no steps, untouched workdir."""
    return RunResult(
        trace=Trace(started_at=0.0, ended_at=1.0, finished=True,
                    interrupted_reason=None, n_service_errors=1, steps=[]),
        raw_session=None,
    )


def _cut_short_result() -> RunResult:
    """The agent was WORKING when the provider failed — steps recorded, then a 407.

    This is the shape observed in a real container run: a gradle suite ran for
    minutes, the connection idled, and the gateway demanded re-auth on the next
    model call. The recorded cost describes where the infrastructure interrupted the
    agent, so the sample is invalid rather than informative.
    """
    from abench.trace_model import Step
    return RunResult(
        trace=Trace(started_at=0.0, ended_at=1.0, finished=False,
                    interrupted_reason="error", n_service_errors=1,
                    steps=[Step(kind="tool_call", tool_name="bash")]),
        raw_session=None,
    )


def test_retries_a_session_the_provider_cut_short(tmp_path):
    """A provider error mid-session must re-SAMPLE, not be scored.

    Scoring it charges the arm for where the proxy happened to strike — which is how
    a picocli A/B came back with baseline 0/2 after both its reps were killed. Every
    attempt gets a fresh workdir, so this is a new sample rather than a second
    attempt at the task for the agent, and it applies to both arms alike.
    """
    exp = _experiment(tmp_path, retries=2)
    client = _SequenceClient([_cut_short_result(), _success_result()])
    run_experiment(exp, client_factory=lambda e: client)
    assert client.calls == 2, "a cut-short session was scored instead of re-sampled"


def test_retries_a_session_that_never_started(tmp_path):
    exp = _experiment(tmp_path, retries=2)
    client = _SequenceClient([_stillborn_result(), _success_result()])
    run_experiment(exp, client_factory=lambda e: client)
    assert client.calls == 2


def test_a_clean_failure_is_not_retried(tmp_path):
    """No provider error means the agent genuinely finished that way — keep it.

    Retrying here WOULD be handing the agent extra attempts, which is exactly the
    unfairness this policy must not introduce.
    """
    from abench.trace_model import Step
    clean_giveup = RunResult(
        trace=Trace(started_at=0.0, ended_at=1.0, finished=True,
                    interrupted_reason=None, n_service_errors=0,
                    steps=[Step(kind="tool_call", tool_name="bash")]),
        raw_session=None,
    )
    exp = _experiment(tmp_path, retries=3)
    client = _SequenceClient([clean_giveup, _success_result()])
    run_experiment(exp, client_factory=lambda e: client)
    assert client.calls == 1, "a clean run was retried — that is an extra attempt"
