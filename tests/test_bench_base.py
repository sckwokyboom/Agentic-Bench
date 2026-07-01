import pytest

from abench.bench.base import (
    Instance, AgentView, TaskSpec, Anchors, EnvSpec, GradeResult,
    assert_no_oracle_leak,
)


def _make_instance() -> Instance:
    return Instance(
        instance_id="x-1",
        repo="r",
        task=TaskSpec(prompt_text="do it"),
        anchors=Anchors(existing_tests=("t",)),
        env=EnvSpec(image="img", build_system="maven"),
        oracle={"gold_patch": "SECRET FIX", "hidden_test_patch": "SECRET TEST"},
    )


def test_agent_view_excludes_oracle():
    view = _make_instance().agent_view()
    assert isinstance(view, AgentView)
    assert not hasattr(view, "oracle")
    assert "SECRET FIX" not in repr(view)
    assert "SECRET TEST" not in repr(view)
    assert_no_oracle_leak(view)


def test_instance_keeps_oracle_for_grading():
    inst = _make_instance()
    assert inst.oracle["gold_patch"] == "SECRET FIX"


def test_agent_view_carries_task_and_anchors():
    view = _make_instance().agent_view()
    assert view.task.prompt_text == "do it"
    assert view.anchors.existing_tests == ("t",)
    assert view.env.build_system == "maven"


def test_guard_ignores_marker_word_in_prompt_text():
    inst = Instance(
        instance_id="x-2", repo="r",
        task=TaskSpec(prompt_text="Fix the gold_patch method and the hidden_test_patch"),
        anchors=Anchors(), env=EnvSpec(image="i", build_system="none"),
    )
    # Must NOT raise: marker words in prompt text are legitimate content.
    assert_no_oracle_leak(inst.agent_view())


def test_grade_result_carries_protocol_flag():
    g = GradeResult(resolved=True, evaluator="e@1", standard_protocol=True)
    assert g.resolved is True
    assert g.standard_protocol is True
    assert g.evaluator == "e@1"
    assert g.official_report == {}
    assert g.abench == {}


def test_guard_fires_on_injected_oracle_attr():
    view = _make_instance().agent_view()
    object.__setattr__(view, "oracle", {"gold_patch": "LEAK"})
    with pytest.raises(AssertionError, match="oracle"):
        assert_no_oracle_leak(view)


def test_envspec_source_dir_default_and_set():
    assert EnvSpec(image="i", build_system="none").source_dir is None
    assert EnvSpec(image="i", build_system="gradle", source_dir="/skel").source_dir == "/skel"
