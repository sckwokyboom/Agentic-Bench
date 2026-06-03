"""Unit tests for service-error counting in the opencode client.

These exercise the pure counting helper directly (no subprocess), so they run
fast and deterministically. The full subprocess path is covered by the
integration smoke test (skipped when opencode is absent).
"""
from abench.opencode_client import _count_service_errors


def test_count_service_errors_counts_top_level_and_part_errors():
    raw_events = [
        {"type": "error", "error": {"statusCode": 429, "message": "rate limited"}},
        {"type": "error", "error": {"statusCode": 503, "message": "unavailable"}},
        {"type": "message", "part": {"type": "text", "text": "hello"}},
        {"part": {"type": "error", "error": {"code": 500}}},
    ]
    n_err, n_rl, msgs = _count_service_errors(raw_events)
    assert n_err == 3          # two top-level + one part-level
    assert n_rl == 1           # only the 429
    assert len(msgs) <= 5
    assert any("429" in m for m in msgs)


def test_count_service_errors_none_when_no_errors():
    raw_events = [
        {"type": "message", "part": {"type": "text", "text": "ok"}},
        {"type": "message", "part": {"type": "tool", "tool": "bash"}},
    ]
    n_err, n_rl, msgs = _count_service_errors(raw_events)
    assert n_err == 0
    assert n_rl == 0
    assert msgs == []


def test_count_service_errors_caps_messages_at_five():
    raw_events = [
        {"type": "error", "error": {"statusCode": 500, "message": f"err {i}"}}
        for i in range(10)
    ]
    n_err, n_rl, msgs = _count_service_errors(raw_events)
    assert n_err == 10
    assert n_rl == 0
    assert len(msgs) == 5


def test_count_service_errors_truncates_long_messages():
    raw_events = [
        {"type": "error", "error": {"message": "x" * 500}},
    ]
    _n_err, _n_rl, msgs = _count_service_errors(raw_events)
    assert len(msgs) == 1
    assert len(msgs[0]) <= 161  # ~160 chars + ellipsis tolerance


def test_count_service_errors_rate_limit_via_status_string():
    raw_events = [
        {"type": "error", "error": {"status": "429"}},
    ]
    n_err, n_rl, _msgs = _count_service_errors(raw_events)
    assert n_err == 1
    assert n_rl == 1
