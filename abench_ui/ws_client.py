"""WSPublishingClient — wraps any OpenCodeClient and publishes every raw
event to a callback as well as the inner on_event sink."""
from __future__ import annotations

from typing import Callable

from abench.opencode_client import OpenCodeClient, RunResult


class WSPublishingClient:
    def __init__(self, inner: OpenCodeClient, publish: Callable[[dict], None]):
        self._inner = inner
        self._publish = publish

    def run_task(
        self,
        *,
        workdir: str,
        system_prompt: str,
        model: str,
        user_message: str,
        timeout_s: int,
        agent_tools: "dict[str, bool] | None" = None,
        on_event: Callable[[dict], None],
        log_sink: Callable[[str], None] | None = None,
        cancel_event=None,
    ) -> RunResult:
        def on_event_relay(event: dict) -> None:
            self._publish(event)
            on_event(event)
        return self._inner.run_task(
            workdir=workdir, system_prompt=system_prompt, model=model,
            user_message=user_message, timeout_s=timeout_s, agent_tools=agent_tools,
            on_event=on_event_relay, log_sink=log_sink, cancel_event=cancel_event,
        )
