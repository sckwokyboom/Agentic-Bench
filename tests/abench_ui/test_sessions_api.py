"""GET /api/sessions (active list) + enriched GET /api/sessions/{sid} so a live
run can be re-opened by sid alone after the tab was closed."""
import textwrap
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from abench.opencode_client import RunResult
from abench.trace_model import Trace
from abench_ui.server import create_app


def _scaffold(root: Path) -> None:
    d = root / "exp-s"
    (d / "prompts").mkdir(parents=True)
    (d / "prompts" / "task.md").write_text("t")
    (d / "prompts" / "system.md").write_text("s")
    (d / "original").mkdir()
    (d / "original" / "a.py").write_text("x")
    (d / "stripped").mkdir()
    (d / "stripped" / "a.py").write_text("x")
    (d / "experiment.yaml").write_text(textwrap.dedent("""\
        name: exp-s
        fixture_path: ./stripped
        reference_path: ./original
        task_prompt: ./prompts/task.md
        system_prompt: ./prompts/system.md
        model: opencode/deepseek-v4-flash-free
        repetitions: 1
        output_dir: ./runs
        conditions:
          - {name: baseline, augmentation: null}
        verify:
          enabled: false
        isolation:
          nonce_prefix: false
          shuffle_order: false
    """))


class _BlockingClient:
    """Emits one event then blocks in run_task until released, so the session
    stays RUNNING long enough to assert it is listed as active."""

    def __init__(self, release: threading.Event):
        self._release = release

    def run_task(self, *, on_event, **_kw) -> RunResult:
        on_event({"type": "message.start"})
        self._release.wait(timeout=10)
        return RunResult(
            trace=Trace(started_at=0.0, ended_at=1.0, finished=True,
                        interrupted_reason=None),
            raw_session={},
        )


def _wait(predicate, timeout=8.0, step=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        val = predicate()
        if val:
            return val
        time.sleep(step)
    return predicate()


def test_active_sessions_lists_running_then_excludes_finished(tmp_path):
    _scaffold(tmp_path)
    release = threading.Event()
    app = create_app(
        experiments_dir=tmp_path,
        client_factory_override=lambda e: _BlockingClient(release),
    )
    client = TestClient(app)
    sid = client.post("/api/runs", json={"experiment_name": "exp-s"}).json()[
        "session_id"]

    # The running session shows up with full experiment context.
    found = _wait(lambda: next(
        (s for s in client.get("/api/sessions").json()
         if s["session_id"] == sid), None))
    assert found is not None, "running session not listed by /api/sessions"
    assert found["experiment_name"] == "exp-s"
    assert found["state"] in ("running", "pending")
    assert found["batch_id"]
    assert found["conditions"] == ["baseline"]
    assert found["total_runs"] == 1

    # The single-session endpoint is enriched identically (re-open by sid).
    one = client.get(f"/api/sessions/{sid}").json()
    assert one["experiment_name"] == "exp-s"
    assert one["batch_id"] == found["batch_id"]
    assert one["conditions"] == ["baseline"]

    # Once it finishes it drops out of the active list (but is still fetchable).
    release.set()
    _wait(lambda: client.get(f"/api/sessions/{sid}").json()["state"]
          == "completed")
    assert all(s["session_id"] != sid for s in client.get("/api/sessions").json())
    assert client.get(f"/api/sessions/{sid}").json()["experiment_name"] == "exp-s"


def test_active_sessions_empty_by_default(tmp_path):
    _scaffold(tmp_path)
    app = create_app(experiments_dir=tmp_path)
    client = TestClient(app)
    assert client.get("/api/sessions").json() == []


def test_unknown_session_404(tmp_path):
    _scaffold(tmp_path)
    app = create_app(experiments_dir=tmp_path)
    client = TestClient(app)
    assert client.get("/api/sessions/nope").status_code == 404
