# tests/fakes.py
from __future__ import annotations

from pathlib import Path
from typing import Callable

from abench.opencode_client import RunResult
from abench.trace_model import Step, StepKind, Trace


class FakeOpenCodeClient:
    """Deterministic stand-in for the real client. Simulates a 2-turn run that
    reads a file, edits one file, and runs tests once."""

    def run_task(self, *, workdir: str, system_prompt: str, model: str,
                 user_message: str, timeout_s: int,
                 on_event: Callable[[dict], None],
                 log_sink: Callable[[str], None] | None = None,
                 debug_sink: Callable[[str], None] | None = None,
                 cancel_event=None) -> RunResult:
        if log_sink is not None:
            log_sink("[fake] starting task")
        on_event({"type": "message.start"})
        (Path(workdir) / "GENERATED.txt").write_text("generated body\n")
        on_event({"type": "tool.finish", "tool": "write"})
        trace = Trace(
            started_at=0.0,
            ended_at=3.0,
            tokens_in=50,
            tokens_out=75,
            finished=True,
            steps=[
                Step(kind=StepKind.ASSISTANT_TEXT, ts=0.0, turn=0, text="plan"),
                Step(kind=StepKind.TOOL_CALL, ts=1.0, turn=0,
                     tool_name="read", tool_args={"path": "GENERATED.txt"}),
                Step(kind=StepKind.FILE_EDIT, ts=2.0, turn=1,
                     path="GENERATED.txt", patch="+generated body"),
                Step(kind=StepKind.TOOL_CALL, ts=2.5, turn=1,
                     tool_name="bash", tool_args={"command": "pytest -q"}),
            ],
        )
        return RunResult(trace=trace, raw_session={"fake": True})
