import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from abench_ui.server import create_app


def _scaffold_minimal_exp(root: Path):
    d = root / "exp-ws"
    d.mkdir()
    (d / "prompts").mkdir()
    (d / "slices").mkdir()
    (d / "prompts" / "task.md").write_text("t")
    (d / "prompts" / "system.md").write_text("s")
    (d / "original").mkdir()
    (d / "original" / "a.py").write_text("x")
    (d / "stripped").mkdir()
    (d / "stripped" / "a.py").write_text("x")
    (d / "experiment.yaml").write_text(textwrap.dedent("""\
        name: exp-ws
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


def test_ws_publishes_session_lifecycle(tmp_path):
    _scaffold_minimal_exp(tmp_path)
    # Inject a fake client factory so the run completes synchronously without
    # actually calling opencode.
    from tests.fakes import FakeOpenCodeClient
    app = create_app(
        experiments_dir=tmp_path,
        client_factory_override=lambda e: FakeOpenCodeClient(),
    )
    client = TestClient(app)

    r = client.post("/api/runs", json={"experiment_name": "exp-ws"})
    assert r.status_code == 200
    sid = r.json()["session_id"]

    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        # Drain messages until session.finished
        types_seen: list[str] = []
        while True:
            msg = ws.receive_json(mode="text")
            types_seen.append(msg["type"])
            if msg["type"] == "session.finished":
                break
            if len(types_seen) > 200:
                pytest.fail(f"too many events: {types_seen}")
    assert "session.started" in types_seen
    assert "run.started" in types_seen
    assert "raw_event" in types_seen
    assert "run.finished" in types_seen


def test_envelopes_carry_condition_and_rep(tmp_path):
    _scaffold_minimal_exp(tmp_path)
    from tests.fakes import FakeOpenCodeClient
    app = create_app(
        experiments_dir=tmp_path,
        client_factory_override=lambda e: FakeOpenCodeClient(),
    )
    client = TestClient(app)
    r = client.post("/api/runs", json={"experiment_name": "exp-ws"})
    sid = r.json()["session_id"]

    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        run_starteds = []
        while True:
            msg = ws.receive_json(mode="text")
            if msg["type"] == "run.started":
                run_starteds.append(msg)
            if msg["type"] == "session.finished":
                break
    assert run_starteds
    for m in run_starteds:
        assert "condition" in m
        assert "rep" in m
        assert m["condition"] == "baseline"


def test_run_finished_carries_duration(tmp_path):
    """run.finished includes duration_s (agent wall-clock seconds) so the UI can
    estimate remaining time. The fake trace runs 0.0→3.0s → duration_s == 3.0."""
    _scaffold_minimal_exp(tmp_path)
    from tests.fakes import FakeOpenCodeClient
    app = create_app(
        experiments_dir=tmp_path,
        client_factory_override=lambda e: FakeOpenCodeClient(),
    )
    client = TestClient(app)
    sid = client.post("/api/runs", json={"experiment_name": "exp-ws"}).json()[
        "session_id"]

    finished = None
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        while True:
            msg = ws.receive_json(mode="text")
            if msg["type"] == "run.finished":
                finished = msg
            if msg["type"] == "session.finished":
                break
    assert finished is not None
    assert finished["duration_s"] == 3.0


def test_ws_unknown_session_sends_error_then_closes(tmp_path):
    """An unknown/expired session (e.g. after a server restart) must get an
    explicit session.error envelope + a close, so the client shows a message and
    stops reconnecting instead of looping open/close forever."""
    from starlette.websockets import WebSocketDisconnect
    _scaffold_minimal_exp(tmp_path)
    app = create_app(experiments_dir=tmp_path)
    client = TestClient(app)
    with client.websocket_connect("/ws/sessions/does-not-exist") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "session.error"
        assert "no longer available" in msg["message"].lower()
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
