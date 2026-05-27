# abench/opencode_client.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from .trace_model import Trace


@dataclass
class RunResult:
    trace: Trace
    raw_session: dict | None = None


class OpenCodeClient(Protocol):
    def run_task(
        self,
        *,
        workdir: str,
        system_prompt: str,
        model: str,
        user_message: str,
        timeout_s: int,
        on_event: Callable[[dict], None],
    ) -> RunResult:
        ...
