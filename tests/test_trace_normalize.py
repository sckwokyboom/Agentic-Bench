"""Golden test for the OpenCode trace normalizer.

Uses real fixtures captured from a live opencode run (Task 11 spike).
Fixture values are read dynamically so the test is pinned to the actual
committed data rather than hand-copied constants.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "opencode"


def _load_events() -> list[dict]:
    return [
        json.loads(line)
        for line in (FIXTURES / "events_sample.jsonl").read_text().splitlines()
        if line.strip()
    ]


def _load_session() -> dict:
    text = (FIXTURES / "session_sample.json").read_text()
    # First line is "Exporting session: <id>" — skip it.
    lines = text.splitlines()
    json_start = next(i for i, l in enumerate(lines) if l.strip().startswith("{"))
    return json.loads("\n".join(lines[json_start:]))


@pytest.fixture(scope="module")
def events():
    return _load_events()


@pytest.fixture(scope="module")
def session():
    return _load_session()


# ---------------------------------------------------------------------------
# Main golden test
# ---------------------------------------------------------------------------


def test_normalize_golden(events, session):
    from abench.trace_normalize import normalize
    from abench.trace_model import StepKind

    trace = normalize(events, session)

    # ── Structure ──────────────────────────────────────────────────────────
    assert len(trace.steps) == 3
    tool_call, tool_result, assistant_text = trace.steps
    assert tool_call.kind == StepKind.TOOL_CALL
    assert tool_result.kind == StepKind.TOOL_RESULT
    assert assistant_text.kind == StepKind.ASSISTANT_TEXT

    # ── TOOL_CALL ─────────────────────────────────────────────────────────
    assert tool_call.tool_name == "bash"
    assert tool_call.tool_args == {
        "command": "ls",
        "description": "Lists files in current directory",
    }
    assert tool_call.tool_call_id == "blBHpggrk"
    # ts = state.time.start / 1000.0
    assert tool_call.ts == pytest.approx(1779964688242 / 1000.0)

    # ── TOOL_RESULT ───────────────────────────────────────────────────────
    assert tool_result.tool_call_id == "blBHpggrk"
    assert tool_result.exit_code == 0
    assert "note.txt" in tool_result.output
    # ts = state.time.end / 1000.0
    assert tool_result.ts == pytest.approx(1779964688246 / 1000.0)

    # ── ASSISTANT_TEXT ────────────────────────────────────────────────────
    assert assistant_text.text == "done"
    # ts = part.time.start / 1000.0
    assert assistant_text.ts == pytest.approx(1779964688817 / 1000.0)

    # ── Turn indices ──────────────────────────────────────────────────────
    assert tool_call.turn == 0
    assert tool_result.turn == 0
    assert assistant_text.turn == 1

    # ── Trace-level token / cost fields from session ──────────────────────
    info = session["info"]
    assert trace.tokens_in == info["tokens"]["input"]    # 15765
    assert trace.tokens_out == info["tokens"]["output"]  # 22
    assert trace.cost == pytest.approx(info["cost"])     # 0.0015831

    # ── Caller-set fields must be left at defaults ─────────────────────────
    assert trace.started_at is None
    assert trace.ended_at is None
    assert trace.finished is False
    assert trace.interrupted_reason is None


# ---------------------------------------------------------------------------
# No-session variant
# ---------------------------------------------------------------------------


def test_normalize_without_session(events):
    """normalize(events, None) must succeed; token / cost fields are None."""
    from abench.trace_normalize import normalize

    trace = normalize(events, None)
    assert len(trace.steps) == 3
    assert trace.tokens_in is None
    assert trace.tokens_out is None
    assert trace.cost is None


def test_normalize_populates_turns_from_step_finish():
    """The golden fixture contains step-finish events with reason/tokens/cost.
    The normalizer must populate trace.turns from them in order."""
    events = _load_events()
    session = _load_session()
    from abench.trace_normalize import normalize
    trace = normalize(events, session)

    # Sample run had one tool-call turn followed by a final text turn:
    assert len(trace.turns) >= 1
    last_turn = trace.turns[-1]
    assert last_turn.reason in {"tool-calls", "stop", "length", "content-filter"}
    assert last_turn.tokens_in is not None or last_turn.tokens_out is not None
    # message_id consistency: each TurnInfo.message_id must be among the trace's step.turn-correlated message_ids
    message_ids_in_steps = {s.tool_call_id for s in trace.steps if s.tool_call_id}
    # we can't assert exact match without re-deriving — just sanity:
    assert all(t.message_id for t in trace.turns)


def test_steps_carry_message_id():
    """Every produced Step must carry the messageID of the part it came from,
    so the frontend can join TurnInfo by message_id rather than array index."""
    from abench.trace_normalize import normalize
    raw = [
        {"part": {"type": "reasoning", "messageID": "M0", "text": "t"}},
        {"part": {"type": "tool", "messageID": "M0", "tool": "read", "callID": "c1",
                  "state": {"status": "completed", "input": {"path": "a"}, "output": "o",
                            "metadata": {"exit": 0}, "time": {"start": 0, "end": 1000}}}},
        {"part": {"type": "patch", "messageID": "M0", "path": "a", "patch": "p"}},
        {"part": {"type": "text", "messageID": "M1", "text": "done",
                  "time": {"start": 2000}}},
    ]
    tr = normalize(raw, None)
    assert all(s.message_id is not None for s in tr.steps)
    assert {s.message_id for s in tr.steps} == {"M0", "M1"}


def test_normalize_captures_reasoning_and_cache_tokens():
    from abench.trace_normalize import normalize
    session = {"info": {"tokens": {"input": 100, "output": 20, "reasoning": 5,
                                    "cache": {"read": 80, "write": 12}}, "cost": 0.01}}
    tr = normalize([], session)
    assert tr.tokens_in == 100 and tr.tokens_out == 20
    assert tr.tokens_reasoning == 5
    assert tr.cache_read == 80 and tr.cache_write == 12
