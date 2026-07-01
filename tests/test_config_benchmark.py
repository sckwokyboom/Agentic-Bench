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


from pathlib import Path

from abench.config import load_experiment


def test_load_experiment_benchmark_yaml(tmp_path: Path):
    (tmp_path / "data.json").write_text("[]")
    (tmp_path / "exp.yaml").write_text(
        "name: t\n"
        "benchmark:\n"
        "  adapter: smoke\n"
        "  dataset: ./data.json\n"
        "task_prompt: solve it\n"
        "system_prompt: be good\n"
        "model: deepseek/deepseek-v4-flash\n"
        "output_dir: ./runs\n"
        "conditions:\n"
        "  - {name: baseline}\n"
    )
    exp = load_experiment(tmp_path / "exp.yaml")
    assert exp.benchmark.adapter == "smoke"
    assert exp.benchmark.dataset == (tmp_path / "data.json").resolve()
    assert exp.fixture_path is None


def test_load_experiment_unknown_adapter_rejected(tmp_path: Path):
    (tmp_path / "exp.yaml").write_text(
        "name: t\n"
        "benchmark:\n"
        "  adapter: does-not-exist\n"
        "task_prompt: p\n"
        "system_prompt: s\n"
        "model: m\n"
        "output_dir: ./runs\n"
        "conditions:\n"
        "  - {name: baseline}\n"
    )
    with pytest.raises(ValueError):
        load_experiment(tmp_path / "exp.yaml")
