import threading
import time
from pathlib import Path

from abench.config import Condition, Experiment, IsolationCfg, MetricsCfg, OpenCodeCfg, VerifyCfg
from abench.opencode_client import RunResult
from abench.trace_model import Trace
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
    # session.started carries the experiment's model so the live run can show it
    assert started["model"] == exp.model

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


class _BlockUntilCancelClient:
    """A client whose run_task blocks until the cancel_event is set, then
    returns a cancelled trace. Proves the cancel Event is threaded all the way
    down to run_task and unblocks the run."""

    def __init__(self, started: threading.Event):
        self._started = started

    def run_task(self, *, workdir, system_prompt, model, user_message,
                 timeout_s, agent_tools=None, on_event, log_sink=None, debug_sink=None, cancel_event=None,
                 temperature=None):
        self._started.set()
        while not (cancel_event is not None and cancel_event.is_set()):
            time.sleep(0.01)
        return RunResult(
            trace=Trace(interrupted_reason="cancelled", finished=False),
        )


def test_run_session_cancel_unblocks_run_and_sets_cancelled(tmp_path):
    """Cancel must reach run_task (via the cancel Event) and unblock the run,
    leaving the session CANCELLED — not a no-op."""
    exp = _make_exp(tmp_path)
    started = threading.Event()
    session = RunSession(
        id="sess-cancel-real",
        experiment=exp,
        client_factory=lambda e: _BlockUntilCancelClient(started),
        publish=lambda _ev: None,
    )
    session.start()
    assert started.wait(timeout=5), "run_task never started"
    session.cancel()
    session._thread.join(timeout=5)
    assert session._thread is not None
    assert not session._thread.is_alive(), "run thread did not finish after cancel"
    assert session.state == SessionState.CANCELLED


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


class _ValidityClient:
    """Stub client whose trace carries service errors + a non-empty
    final_diff_summary, so the run.finished envelope can surface the new
    validity fields."""

    def run_task(self, *, workdir, system_prompt, model, user_message,
                 timeout_s, agent_tools=None, on_event, log_sink=None, debug_sink=None, cancel_event=None,
                 temperature=None):
        from pathlib import Path as _Path

        from abench.opencode_client import RunResult
        from abench.trace_model import (
            FileChange,
            FinalDiffSummary,
            Step,
            StepKind,
            Trace,
        )

        if log_sink is not None:
            log_sink("[stub] starting task")
        on_event({"type": "message.start"})
        (_Path(workdir) / "a.py").write_text("x = 2\n")  # mutate the fixture
        trace = Trace(
            started_at=0.0, ended_at=1.0, finished=True,
            n_service_errors=2, n_rate_limits=1, verify_insensitive=True,
            steps=[Step(kind=StepKind.FILE_EDIT, ts=1.0, turn=0,
                        path="a.py", patch="+x = 2")],
        )
        # The runner overwrites final_diff_summary from the real patch, but set
        # one here too so the trace is self-describing if read directly.
        trace.final_diff_summary = FinalDiffSummary(
            files=[FileChange(path="a.py", added=1, removed=1)],
            total_added=1, total_removed=1,
        )
        return RunResult(trace=trace, raw_session={"stub": True})


def test_run_finished_envelope_surfaces_validity_fields(tmp_path):
    """run.finished carries n_service_errors + made_source_changes
    (the latter derived from the trace's final_diff_summary)."""
    exp = _make_exp(tmp_path)
    published: list[dict] = []
    session = RunSession(
        id="sess-validity",
        experiment=exp,
        client_factory=lambda e: _ValidityClient(),
        publish=published.append,
    )
    session.start()
    for _ in range(50):
        if session.state in (SessionState.COMPLETED, SessionState.FAILED):
            break
        time.sleep(0.1)
    assert session.state == SessionState.COMPLETED

    finished = next(m for m in published if m["type"] == "run.finished")
    assert finished["n_service_errors"] == 2
    assert finished["made_source_changes"] is True
    assert finished["verify_insensitive"] is True


def test_per_run_publishing_groups_phase_subcalls_by_workdir():
    """Regression: phased orchestration calls run_task once per phase, all on
    the SAME workdir. The wrapper must treat that as ONE run (one run.started,
    one plan slot) — counting per call overran self._plan and raised
    'IndexError: list index out of range', crashing every phased run."""
    from abench_ui.run_session import _PerRunPublishingClient

    plan = [(Condition(name="phased", augmentation=None), 0),
            (Condition(name="phased", augmentation=None), 1)]
    published: list[dict] = []
    positions: list[tuple] = []

    class _Inner:
        def run_task(self, *, workdir, on_event, **kw):
            on_event({"type": "phase-event"})
            return RunResult(trace=Trace(finished=True), raw_session=None)

    w = _PerRunPublishingClient(
        _Inner(), published.append, session_id="sid", total_runs=2, plan=plan,
        position_callback=lambda i, c, r: positions.append((i, c, r)),
        batch_id="b")

    common = dict(system_prompt="s", model="m", user_message="u", timeout_s=1,
                  on_event=lambda e: None)
    # run 0: THREE phase calls on one workdir (would have crashed on the 3rd
    # call — self._plan[2] over a 2-entry plan — before the fix)
    for _ in range(3):
        w.run_task(workdir="/w/run0", **common)
    # run 1: a NEW workdir advances to the next plan entry
    w.run_task(workdir="/w/run1", **common)

    started = [m for m in published if m["type"] == "run.started"]
    assert len(started) == 2                       # one per RUN, not per call
    assert [s["run_idx"] for s in started] == [1, 2]
    assert [s["rep"] for s in started] == [0, 1]
    assert positions == [(1, "phased", 0), (2, "phased", 1)]
    # all of run 0's phase events carry the same run_idx (one run across phases)
    raw0 = [m for m in published if m["type"] == "raw_event" and m["run_idx"] == 1]
    assert len(raw0) == 3

    # run.finished fires ONCE per run, not per phase: run 0's flushes when run 1's
    # workdir appears; run 1's flushes at session end via flush().
    assert [m for m in published if m["type"] == "run.finished"
            and m["run_idx"] == 1] != []                 # run 0 already flushed
    w.flush()                                            # session end
    finished = [m for m in published if m["type"] == "run.finished"]
    assert len(finished) == 2                            # one per RUN, not per phase
    assert [f["run_idx"] for f in finished] == [1, 2]


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
