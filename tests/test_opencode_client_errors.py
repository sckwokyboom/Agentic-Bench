"""Unit tests for service-error counting in the opencode client.

These exercise the pure counting helper directly (no subprocess), so they run
fast and deterministically. The full subprocess path is covered by the
integration smoke test (skipped when opencode is absent).
"""
from abench.opencode_client import (
    _count_service_errors, _run_deadline, _is_stalled, _MODEL_ERROR_RE,
)


def test_model_error_regex_flags_endpoint_and_auth_failures():
    """The stderr lines we promote to run.log + a live UI model_error phase, so an
    unreachable endpoint or a bad key surfaces instead of a silent 'waiting'."""
    for bad in ["401 Unauthorized", "connection refused",
                "getaddrinfo ENOTFOUND api.example.com", "request timed out",
                "HTTP 503 from provider", "certificate verify failed",
                "Error connecting to model endpoint"]:
        assert _MODEL_ERROR_RE.search(bad), bad
    for ok in ["INFO service=session starting", "INFO tool call read",
               "model responded with 42 tokens"]:
        assert not _MODEL_ERROR_RE.search(ok), ok


def test_run_deadline_none_or_nonpositive_means_no_limit():
    # No clock: the run ends only on natural completion or cancel.
    assert _run_deadline(100.0, None) is None
    assert _run_deadline(100.0, 0) is None
    assert _run_deadline(100.0, -5) is None


def test_run_deadline_positive_is_start_plus_timeout():
    assert _run_deadline(100.0, 600) == 700.0


def test_is_stalled_detects_no_output_past_idle_timeout():
    now = 1000.0
    assert _is_stalled(now - 700, 600, now) is True   # silent 700s > 600s
    assert _is_stalled(now - 100, 600, now) is False  # silent 100s, still alive


def test_is_stalled_disabled_when_idle_timeout_none_or_zero():
    now = 1000.0
    assert _is_stalled(now - 99999, None, now) is False
    assert _is_stalled(now - 99999, 0, now) is False


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
