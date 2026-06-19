"""Loop detection. An agent that repeats the same message/action with no
progress is NOT idle (it keeps producing output, so idle_timeout never fires),
yet it burns time forever. We kill such a run — but ONLY on a high-confidence
signal: >= repeat_limit consecutive repeats of a short (<=3-step) cycle of
IDENTICAL full-content step-signatures. Because signatures use the FULL content,
genuine iterative work (which changes content each step) is never flagged."""
from abench.opencode_client import _is_looping, _step_signature


# ── _step_signature: one stable signature per agent "step" ──────────────────
def test_signature_text_uses_full_message():
    e = {"part": {"type": "text", "text": "Let me try X"}}
    assert _step_signature(e) == "text:Let me try X"


def test_signature_tool_keyed_by_name_and_input_when_completed():
    e = {"part": {"type": "tool", "tool": "bash",
                  "state": {"status": "completed", "input": {"command": "impact"}}}}
    sig = _step_signature(e)
    assert sig is not None and sig.startswith("tool:bash:") and "impact" in sig


def test_signature_skips_incomplete_tool_boundaries_and_empty_text():
    assert _step_signature({"part": {"type": "tool", "tool": "bash",
                                     "state": {"status": "running"}}}) is None
    assert _step_signature({"part": {"type": "step-start"}}) is None
    assert _step_signature({"type": "step_finish", "part": {"type": "step-finish"}}) is None
    assert _step_signature({"part": {"type": "text", "text": "   "}}) is None


def test_signature_distinguishes_different_tool_inputs():
    a = _step_signature({"part": {"type": "tool", "tool": "read",
                                  "state": {"status": "completed", "input": {"filePath": "a.java"}}}})
    b = _step_signature({"part": {"type": "tool", "tool": "read",
                                  "state": {"status": "completed", "input": {"filePath": "b.java"}}}})
    assert a != b


# ── _is_looping: high-confidence repeat detection ───────────────────────────
def test_detects_same_message_repeated():
    assert _is_looping(["text:stuck"] * 6, repeat_limit=6) is True


def test_not_looping_below_threshold():
    assert _is_looping(["text:stuck"] * 5, repeat_limit=6) is False


def test_detects_two_step_cycle():
    assert _is_looping(["text:think", "tool:read:x"] * 3, repeat_limit=3) is True


def test_progress_then_stuck_at_tail_is_detected():
    sigs = ["a", "b", "c", "d"] + ["text:stuck"] * 6
    assert _is_looping(sigs, repeat_limit=6) is True


def test_genuine_progress_not_flagged():
    sigs = ["tool:read:f1", "tool:read:f2", "text:a", "tool:edit:e1",
            "tool:bash:t1", "text:b", "tool:bash:t2", "text:c"]
    assert _is_looping(sigs, repeat_limit=6) is False


def test_distinct_inputs_not_flagged():
    assert _is_looping([f"tool:read:{i}" for i in range(20)], repeat_limit=6) is False


def test_three_distinct_then_three_distinct_not_flagged():
    # AAABBB-style runs without a repeating cycle must NOT trip the detector
    assert _is_looping(["a", "a", "a", "b", "b", "b"], repeat_limit=6) is False


def test_disabled_when_limit_zero():
    assert _is_looping(["x"] * 100, repeat_limit=0) is False


def test_opencode_cfg_repeat_limit_default():
    from abench.config import OpenCodeCfg
    assert OpenCodeCfg().repeat_limit == 6
