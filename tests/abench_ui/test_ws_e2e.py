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
