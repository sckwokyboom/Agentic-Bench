import pytest

from abench.config import BenchmarkCfg, Condition, Experiment


def test_benchmark_only_is_valid():
    exp = Experiment(
        name="t",
        benchmark=BenchmarkCfg(adapter="smoke"),
        task_prompt="p",
        system_prompt="s",
        model="m",
        output_dir="out",
        conditions=[Condition(name="baseline")],
    )
    assert exp.benchmark.adapter == "smoke"
    assert exp.fixture_path is None


def test_both_sources_rejected():
    with pytest.raises(Exception):
        Experiment(
            name="t",
            fixture_path="fx",
            reference_path="rf",
            benchmark=BenchmarkCfg(adapter="smoke"),
            task_prompt="p",
            system_prompt="s",
            model="m",
            output_dir="out",
            conditions=[Condition(name="baseline")],
        )


def test_neither_source_rejected():
    with pytest.raises(Exception):
        Experiment(
            name="t",
            task_prompt="p",
            system_prompt="s",
            model="m",
            output_dir="out",
            conditions=[Condition(name="baseline")],
        )


def test_fixture_requires_reference():
    with pytest.raises(Exception):
        Experiment(
            name="t",
            fixture_path="fx",
            task_prompt="p",
            system_prompt="s",
            model="m",
            output_dir="out",
            conditions=[Condition(name="baseline")],
        )
