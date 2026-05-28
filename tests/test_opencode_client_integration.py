"""Integration smoke test for RealOpenCodeClient.

Drives a real ``opencode run`` subprocess with a free model.
Skipped automatically when opencode is not installed.
Wall-clock: ~30–60 s on first run (model cold-start + title generation).
"""
import shutil
from pathlib import Path

import pytest

from abench.config import OpenCodeCfg
from abench.opencode_client import RealOpenCodeClient
from abench.trace_model import StepKind

pytestmark = pytest.mark.skipif(
    shutil.which("opencode") is None, reason="opencode not installed"
)


def test_real_client_runs_trivial_task(tmp_path: Path):
    # Tiny fixture
    (tmp_path / "note.txt").write_text("hello\n")

    events_seen = []
    client = RealOpenCodeClient(OpenCodeCfg(agent="abench"), timeout_s=120)
    result = client.run_task(
        workdir=str(tmp_path),
        system_prompt="You are a terse assistant.",
        model="opencode/deepseek-v4-flash-free",
        user_message="Run 'ls' using the bash tool then reply done.",
        timeout_s=120,
        on_event=events_seen.append,
    )

    # Live stream produced at least one event
    assert len(events_seen) >= 1

    # The trace has at least the assistant text + at least one tool call
    kinds = [s.kind for s in result.trace.steps]
    assert StepKind.ASSISTANT_TEXT in kinds
    assert StepKind.TOOL_CALL in kinds

    # Wall-clock fields populated by the client
    assert result.trace.started_at is not None
    assert result.trace.ended_at is not None
    assert result.trace.ended_at >= result.trace.started_at

    # Successful runs
    assert result.trace.finished is True
    assert result.trace.interrupted_reason is None

    # Session export read (tokens populated)
    assert result.trace.tokens_in is not None and result.trace.tokens_in > 0
