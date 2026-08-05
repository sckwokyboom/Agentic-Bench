"""POST/GET/DELETE /api/queue — run several experiments back to back.

The UI could only start one experiment per click, so a multi-method sweep meant
leaving it. These cover what the queue must guarantee: experiments run STRICTLY one
at a time (concurrent agent sessions would contend for CPU during their verifies, and
duration is a measured quantity), one bad experiment does not take the rest of the
batch down, and a cancel stops what is queued without touching what already ran.
"""
import textwrap
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from abench.opencode_client import RunResult
from abench.trace_model import Trace
from abench_ui.server import create_app


def _scaffold(root: Path, name: str) -> None:
    d = root / name
    (d / "prompts").mkdir(parents=True)
    (d / "prompts" / "task.md").write_text("t")
    (d / "prompts" / "system.md").write_text("s")
    (d / "original").mkdir()
    (d / "original" / "a.py").write_text("x")
    (d / "stripped").mkdir()
    (d / "stripped" / "a.py").write_text("x")
    (d / "experiment.yaml").write_text(textwrap.dedent(f"""\
        name: {name}
        fixture_path: ./stripped
        reference_path: ./original
        task_prompt: ./prompts/task.md
        system_prompt: ./prompts/system.md
        model: opencode/deepseek-v4-flash-free
        repetitions: 1
        output_dir: ./runs
        conditions:
          - {{name: baseline, augmentation: null}}
        verify:
          enabled: false
        isolation:
          nonce_prefix: false
          shuffle_order: false
    """))


class _RecordingClient:
    """Records overlapping sessions so the test can prove they never overlap."""

    live = 0
    max_live = 0
    lock = threading.Lock()

    def __init__(self, *a, **k):
        pass

    def run_task(self, *a, **k):
        with _RecordingClient.lock:
            _RecordingClient.live += 1
            _RecordingClient.max_live = max(_RecordingClient.max_live,
                                            _RecordingClient.live)
        time.sleep(0.15)
        with _RecordingClient.lock:
            _RecordingClient.live -= 1
        return RunResult(trace=Trace(steps=[], finished=True))


def _drain(client: TestClient, timeout: float = 30.0) -> dict:
    """Wait for the queue to stop running and return the final snapshot."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = client.get("/api/queue").json()
        if not snap["running"]:
            return snap
        time.sleep(0.05)
    raise AssertionError("queue did not finish in time")


def test_queue_runs_experiments_one_at_a_time(tmp_path):
    for n in ("exp-a", "exp-b", "exp-c"):
        _scaffold(tmp_path, n)
    app = create_app(experiments_dir=tmp_path)
    app.state.abench["client_factory_override"] = lambda e: _RecordingClient()
    _RecordingClient.live = _RecordingClient.max_live = 0
    c = TestClient(app)

    r = c.post("/api/queue", json={"experiment_names": ["exp-a", "exp-b", "exp-c"]})
    assert r.status_code == 200, r.text
    assert [i["name"] for i in r.json()["items"]] == ["exp-a", "exp-b", "exp-c"]

    final = _drain(c)
    assert [i["state"] for i in final["items"]] == ["completed"] * 3
    # The whole point: never two agent sessions at once.
    assert _RecordingClient.max_live == 1, _RecordingClient.max_live


def test_unknown_experiment_is_rejected_before_anything_starts(tmp_path):
    _scaffold(tmp_path, "exp-a")
    app = create_app(experiments_dir=tmp_path)
    app.state.abench["client_factory_override"] = lambda e: _RecordingClient()
    c = TestClient(app)

    r = c.post("/api/queue", json={"experiment_names": ["exp-a", "nope"]})
    assert r.status_code == 404 and "nope" in r.text
    # Nothing queued, so a good name in the same request did not start either.
    assert c.get("/api/queue").json()["items"] == []


def test_second_queue_is_refused_while_one_runs(tmp_path):
    for n in ("exp-a", "exp-b"):
        _scaffold(tmp_path, n)
    app = create_app(experiments_dir=tmp_path)
    app.state.abench["client_factory_override"] = lambda e: _RecordingClient()
    c = TestClient(app)

    assert c.post("/api/queue", json={"experiment_names": ["exp-a", "exp-b"]}).status_code == 200
    second = c.post("/api/queue", json={"experiment_names": ["exp-a"]})
    assert second.status_code == 409
    _drain(c)


def test_cancel_marks_the_rest_cancelled(tmp_path):
    for n in ("exp-a", "exp-b", "exp-c"):
        _scaffold(tmp_path, n)
    app = create_app(experiments_dir=tmp_path)
    app.state.abench["client_factory_override"] = lambda e: _RecordingClient()
    c = TestClient(app)

    c.post("/api/queue", json={"experiment_names": ["exp-a", "exp-b", "exp-c"]})
    c.delete("/api/queue")
    final = _drain(c)
    assert final["cancelled"] is True
    # Whatever had not started is cancelled; nothing is left dangling as pending.
    assert all(i["state"] != "pending" for i in final["items"]), final["items"]
