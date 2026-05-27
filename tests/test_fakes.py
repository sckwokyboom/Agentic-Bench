# tests/test_fakes.py
from pathlib import Path

from abench.opencode_client import RunResult
from tests.fakes import FakeOpenCodeClient


def test_fake_client_emits_events_edits_workdir_and_returns_trace(tmp_path):
    events = []
    client = FakeOpenCodeClient()
    result = client.run_task(
        workdir=str(tmp_path),
        system_prompt="sys",
        model="m",
        user_message="do it",
        timeout_s=10,
        on_event=events.append,
    )
    assert isinstance(result, RunResult)
    assert result.trace.finished is True
    assert len(result.trace.steps) >= 1
    assert (Path(tmp_path) / "GENERATED.txt").exists()  # simulated edit
    assert len(events) >= 1
