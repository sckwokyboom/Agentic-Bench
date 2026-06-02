"""Normalize raw OpenCode event stream + session export into a Trace.

Schema reference: docs/superpowers/notes/opencode-api.md (sections 4, 6, 8).
Verified against fixtures in tests/fixtures/opencode/.
"""
from __future__ import annotations

from abench.trace_model import Step, StepKind, Trace, TurnInfo


def normalize(raw_events: list[dict], raw_session: dict | None) -> Trace:
    """Convert a list of raw OpenCode events and an optional session export
    into a normalized :class:`Trace`.

    Parameters
    ----------
    raw_events:
        Lines parsed from ``opencode run --format json`` stdout (JSONL).
    raw_session:
        Parsed JSON from ``opencode export <id>``, or *None* when unavailable.
    """
    steps: list[Step] = []
    turns: list[TurnInfo] = []
    seen_message_ids: list[str] = []

    for event in raw_events:
        part = event.get("part", {})
        part_type = part.get("type")
        message_id = part.get("messageID")

        # Determine turn index from messageID ordering.
        if message_id is not None:
            if message_id not in seen_message_ids:
                seen_message_ids.append(message_id)
            turn = seen_message_ids.index(message_id)
        else:
            turn = None

        if part_type == "tool":
            state = part.get("state", {})
            time = state.get("time", {})
            metadata = state.get("metadata", {})

            steps.append(
                Step(
                    kind=StepKind.TOOL_CALL,
                    ts=time.get("start", 0) / 1000.0,
                    turn=turn,
                    tool_name=part.get("tool"),
                    tool_args=state.get("input"),
                    tool_call_id=part.get("callID"),
                )
            )
            steps.append(
                Step(
                    kind=StepKind.TOOL_RESULT,
                    ts=time.get("end", 0) / 1000.0,
                    turn=turn,
                    tool_call_id=part.get("callID"),
                    output=state.get("output"),
                    exit_code=metadata.get("exit"),
                )
            )

        elif part_type == "text":
            time = part.get("time", {})
            steps.append(
                Step(
                    kind=StepKind.ASSISTANT_TEXT,
                    ts=time.get("start", 0) / 1000.0,
                    turn=turn,
                    text=part.get("text"),
                )
            )

        elif part_type == "reasoning":
            steps.append(
                Step(
                    kind=StepKind.REASONING,
                    ts=None,
                    turn=turn,
                    text=part.get("text"),
                )
            )

        elif part_type == "patch":
            steps.append(
                Step(
                    kind=StepKind.FILE_EDIT,
                    ts=None,
                    turn=turn,
                    path=part.get("path"),
                    patch=part.get("patch"),
                )
            )

        elif part_type == "step-finish":
            tokens = part.get("tokens", {}) or {}
            time = part.get("time", {}) or {}
            turns.append(TurnInfo(
                message_id=message_id or "",
                reason=part.get("reason"),
                tokens_in=tokens.get("input"),
                tokens_out=tokens.get("output"),
                tokens_reasoning=tokens.get("reasoning"),
                cost=part.get("cost"),
                started_at=(time.get("start") / 1000.0) if time.get("start") else None,
                ended_at=(time.get("end") / 1000.0) if time.get("end") else None,
            ))
        # step-start and unknown types: skip silently.

    # ── Trace-level fields from session export ─────────────────────────────
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost: float | None = None

    tokens_reasoning: int | None = None
    cache_read: int | None = None
    cache_write: int | None = None
    if raw_session is not None:
        info = raw_session.get("info", {})
        tokens = info.get("tokens", {})
        tokens_in = tokens.get("input")
        tokens_out = tokens.get("output")
        tokens_reasoning = tokens.get("reasoning")
        cache = tokens.get("cache", {}) or {}
        cache_read = cache.get("read")
        cache_write = cache.get("write")
        cost = info.get("cost")

    return Trace(
        steps=steps,
        turns=turns,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        tokens_reasoning=tokens_reasoning,
        cache_read=cache_read,
        cache_write=cache_write,
        cost=cost,
        # started_at, ended_at, finished, interrupted_reason: caller's responsibility.
    )
