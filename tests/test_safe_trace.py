"""Unit tests for abench.safe_trace.safe_trace."""
from abench.safe_trace import Scrubber, safe_trace


def test_safe_trace_exposes_temperature():
    scr = Scrubber()
    out = safe_trace(
        {"temperature": 0.7},
        {},
        scr,
        include_outputs=False,
        max_output_chars=500,
    )
    assert out["temperature"] == 0.7
