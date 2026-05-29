from abench_ui.ws_client import WSPublishingClient
from tests.fakes import FakeOpenCodeClient


def test_wraps_run_task_and_publishes_each_event(tmp_path):
    inner = FakeOpenCodeClient()
    captured = []
    client = WSPublishingClient(inner, publish=captured.append)

    on_events = []
    result = client.run_task(
        workdir=str(tmp_path),
        system_prompt="sys",
        model="m",
        user_message="do it",
        timeout_s=10,
        on_event=on_events.append,
    )
    # Both the inner client's events.jsonl writer AND the publish callback
    # must receive each event.
    assert len(captured) >= 1
    assert len(on_events) == len(captured)
    # Result is the inner client's result, unchanged.
    assert result is not None
    assert result.trace.finished is True
