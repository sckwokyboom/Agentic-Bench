import time
from pathlib import Path

from abench.config import Condition, Experiment, IsolationCfg, MetricsCfg, OpenCodeCfg, VerifyCfg
from abench_ui.run_session import RunSession, SessionState
from tests.fakes import FakeOpenCodeClient


def _make_exp(tmp_path: Path) -> Experiment:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "a.py").write_text("x = 1\n")
    reference = tmp_path / "reference"
    reference.mkdir()
    return Experiment(
        name="rs-test",
        fixture_path=fixture, reference_path=reference,
        task_prompt="t", system_prompt="s", model="m",
        output_dir=tmp_path / "runs", repetitions=1,
        conditions=[Condition(name="baseline", augmentation=None)],
        opencode=OpenCodeCfg(), metrics=MetricsCfg(),
        verify=VerifyCfg(enabled=False),
        isolation=IsolationCfg(nonce_prefix=False, shuffle_order=False),
    )


def test_run_session_runs_to_completion_and_publishes_envelopes(tmp_path):
    exp = _make_exp(tmp_path)
    published: list[dict] = []
    session = RunSession(
        id="sess-1",
        experiment=exp,
        client_factory=lambda e: FakeOpenCodeClient(),
        publish=published.append,
    )
    session.start()
    # Wait up to 5s for completion
    for _ in range(50):
        if session.state in (SessionState.COMPLETED, SessionState.FAILED):
            break
        time.sleep(0.1)
    assert session.state == SessionState.COMPLETED

    types = [m["type"] for m in published]
    assert types[0] == "session.started"
    assert "run.started" in types
    assert "raw_event" in types
    assert "run.finished" in types
    assert types[-1] == "session.finished"

    # session.started carries the batch id + the experiment's isolation config
    started = published[0]
    assert started["batch_id"] == session.batch_id
    assert started["batch_id"]  # non-empty
    assert started["isolation"] == {"nonce_prefix": False, "shuffle_order": False}

    # run.finished carries the same batch id (Task 3/4 consume it)
    finished = next(m for m in published if m["type"] == "run.finished")
    assert finished["batch_id"] == session.batch_id


def test_run_session_uses_explicit_batch_id(tmp_path):
    exp = _make_exp(tmp_path)
    published: list[dict] = []
    session = RunSession(
        id="sess-batch",
        experiment=exp,
        client_factory=lambda e: FakeOpenCodeClient(),
        publish=published.append,
        batch_id="20260601-120000",
    )
    assert session.batch_id == "20260601-120000"
    session.start()
    for _ in range(50):
        if session.state in (SessionState.COMPLETED, SessionState.FAILED):
            break
        time.sleep(0.1)
    assert session.state == SessionState.COMPLETED
    # The run was written under the explicit batch id.
    run_dir = exp.output_dir / exp.name / "20260601-120000" / "baseline" / "rep_0"
    assert (run_dir / "metrics.json").is_file()
    assert published[0]["batch_id"] == "20260601-120000"


def test_run_session_cancel_marks_state(tmp_path):
    """Best-effort cancel — set the flag; the run still wraps up cleanly."""
    exp = _make_exp(tmp_path)
    session = RunSession(
        id="sess-2", experiment=exp,
        client_factory=lambda e: FakeOpenCodeClient(),
        publish=lambda _ev: None,
    )
    session.start()
    session.cancel()
    # cancel is best-effort; eventually state is COMPLETED or CANCELLED
    for _ in range(50):
        if session.state in (SessionState.COMPLETED, SessionState.FAILED, SessionState.CANCELLED):
            break
        time.sleep(0.1)
    assert session.state in (SessionState.COMPLETED, SessionState.CANCELLED)


def test_run_session_error_publishes_session_error(tmp_path):
    """If the experiment raises, state is FAILED and session.error is published."""
    exp = _make_exp(tmp_path)
    published: list[dict] = []

    def bad_factory(e):
        raise RuntimeError("boom")

    session = RunSession(
        id="sess-3", experiment=exp,
        client_factory=bad_factory,
        publish=published.append,
    )
    session.start()
    for _ in range(50):
        if session.state in (SessionState.COMPLETED, SessionState.FAILED, SessionState.CANCELLED):
            break
        time.sleep(0.1)
    assert session.state == SessionState.FAILED
    types = [m["type"] for m in published]
    assert "session.error" in types
    assert types[-1] == "session.finished"


def test_run_session_properties(tmp_path):
    """started_at / ended_at are set correctly."""
    exp = _make_exp(tmp_path)
    session = RunSession(
        id="sess-4", experiment=exp,
        client_factory=lambda e: FakeOpenCodeClient(),
        publish=lambda _ev: None,
    )
    assert session.started_at is None
    assert session.ended_at is None
    session.start()
    for _ in range(50):
        if session.state in (SessionState.COMPLETED, SessionState.FAILED):
            break
        time.sleep(0.1)
    assert session.started_at is not None
    assert session.ended_at is not None
    assert session.ended_at >= session.started_at
