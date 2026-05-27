# tests/test_prompt.py
from abench.prompt import compose


def test_compose_baseline_returns_task_only():
    assert compose("Fix the bug.", None) == "Fix the bug."
    assert compose("Fix the bug.", "") == "Fix the bug."


def test_compose_augmented_appends_block():
    out = compose("Fix the bug.", "GRAPH SLICE\nnode A -> B")
    assert out == "Fix the bug.\n\n---\n\nGRAPH SLICE\nnode A -> B"
