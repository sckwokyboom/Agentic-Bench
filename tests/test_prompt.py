# tests/test_prompt.py
from abench.prompt import GROUNDING_GUARD, build_system_prompt, compose


def test_compose_baseline_returns_task_only():
    assert compose("Fix the bug.", None) == "Fix the bug."
    assert compose("Fix the bug.", "") == "Fix the bug."


def test_compose_augmented_appends_block():
    out = compose("Fix the bug.", "GRAPH SLICE\nnode A -> B")
    assert out == "Fix the bug.\n\n---\n\nGRAPH SLICE\nnode A -> B"


def test_build_system_prompt_plain_passthrough():
    # No guard, no nonce → the base prompt is returned verbatim.
    assert build_system_prompt("BASE", forbid_external_sources=False) == "BASE"


def test_build_system_prompt_guard_first_then_base():
    out = build_system_prompt("BASE", forbid_external_sources=True)
    assert out.startswith("# Ground rules")
    assert out == f"{GROUNDING_GUARD}\n\nBASE"
    # The guard forbids the leak vectors we care about.
    assert ".git" in out
    assert "internet" in out


def test_build_system_prompt_order_guard_nonce_base():
    out = build_system_prompt(
        "BASE", nonce="abc", fixture_sha="deadbeef",
        forbid_external_sources=True,
    )
    assert out.startswith("# Ground rules")
    assert "# abench-run: abc\n# fixture: deadbeef" in out
    # guard ... then nonce ... then base, in that order
    assert out.index("Ground rules") < out.index("abench-run") < out.index("BASE")


def test_build_system_prompt_nonce_only_when_guard_off():
    out = build_system_prompt(
        "BASE", nonce="abc", fixture_sha="sha", forbid_external_sources=False,
    )
    assert out == "# abench-run: abc\n# fixture: sha\n\nBASE"


def test_build_system_prompt_handles_empty_base():
    out = build_system_prompt("", forbid_external_sources=True)
    assert out == GROUNDING_GUARD


def test_guard_allows_harness_provided_tools():
    assert "provided by the harness" in GROUNDING_GUARD
