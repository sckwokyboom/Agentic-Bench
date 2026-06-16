# tests/test_run_subset.py
"""Restrict a run to a subset of conditions and/or override the repetition count
(so the UI can run e.g. just `augmented-tool` x1 from a 4x3 experiment without a
separate yaml). apply_run_subset mutates the loaded Experiment in place; the
runner's compute_plan then naturally produces the reduced plan."""
import pytest

from abench.config import Condition, Experiment, MetricsCfg, OpenCodeCfg
from abench.runner import apply_run_subset


def _exp(tmp_path, reps=3):
    return Experiment(
        name="x", fixture_path=tmp_path / "f", reference_path=tmp_path / "r",
        task_prompt="t", system_prompt="s", model="m",
        output_dir=tmp_path / "o", repetitions=reps,
        conditions=[
            Condition(name="baseline", tools=[]),
            Condition(name="augmented", tools=[]),
            Condition(name="augmented-tool", tools=["impact"]),
        ],
        opencode=OpenCodeCfg(), metrics=MetricsCfg())


def test_filters_to_selected_conditions(tmp_path):
    exp = _exp(tmp_path)
    apply_run_subset(exp, ["augmented-tool"], None)
    assert [c.name for c in exp.conditions] == ["augmented-tool"]
    assert exp.repetitions == 3  # untouched


def test_overrides_repetitions(tmp_path):
    exp = _exp(tmp_path)
    apply_run_subset(exp, None, 1)
    assert exp.repetitions == 1
    assert len(exp.conditions) == 3  # untouched


def test_both_filter_and_reps(tmp_path):
    exp = _exp(tmp_path)
    apply_run_subset(exp, ["baseline", "augmented-tool"], 1)
    assert [c.name for c in exp.conditions] == ["baseline", "augmented-tool"]
    assert exp.repetitions == 1


def test_none_is_noop(tmp_path):
    exp = _exp(tmp_path)
    apply_run_subset(exp, None, None)
    assert len(exp.conditions) == 3 and exp.repetitions == 3


def test_unknown_condition_raises(tmp_path):
    with pytest.raises(ValueError, match="unknown"):
        apply_run_subset(_exp(tmp_path), ["ghost"], None)


def test_empty_selection_raises(tmp_path):
    with pytest.raises(ValueError, match="no conditions"):
        apply_run_subset(_exp(tmp_path), [], None)


def test_bad_repetitions_raises(tmp_path):
    with pytest.raises(ValueError):
        apply_run_subset(_exp(tmp_path), None, 0)
