from pathlib import Path

from abench.config import BenchmarkCfg, Condition, Experiment, MetricsCfg
from abench.metrics import MetricsConfig
from abench.bench.run import run_benchmark


class _RecordingClient:
    def __init__(self):
        self.system_prompts = []

    def run_task(self, **kwargs):
        self.system_prompts.append(kwargs["system_prompt"])
        Path(kwargs["workdir"], "calc.py").write_text("def add(a, b):\n    return a + b\n")
        from tests.fakes import FakeOpenCodeClient
        return FakeOpenCodeClient().run_task(**kwargs)


def _exp(tmp_path):
    return Experiment(
        name="smoke-bench", benchmark=BenchmarkCfg(adapter="smoke"),
        task_prompt="(unused)", system_prompt="BASE SYSTEM PROMPT",
        model="fake/model", output_dir=str(tmp_path / "runs"),
        repetitions=1, conditions=[Condition(name="baseline")],
    )


def test_benchmark_system_prompt_has_grounding_guard(tmp_path):
    exp = _exp(tmp_path)
    client = _RecordingClient()
    root = tmp_path / "root"; root.mkdir()
    run_benchmark(exp, client, MetricsConfig(**MetricsCfg().model_dump()), {}, root)
    sp = client.system_prompts[0]
    assert "BASE SYSTEM PROMPT" in sp
    # the grounding guard is present (forbid_external_sources defaults True).
    assert "# Ground rules (do not violate)" in sp


def test_benchmark_mode_refuses_orchestrated_conditions():
    # bench/run.py calls the agent directly — no orchestration dispatch. Accepting
    # `orchestration: rcc` here would run BASELINE and label it 'rcc', the same silent
    # treatment-substitution rcc_strict exists to prevent. Refuse at load time.
    import pytest
    from abench.config import BenchmarkCfg, Condition, Experiment, _validate
    from pathlib import Path
    exp = Experiment(
        name="x", benchmark=BenchmarkCfg(adapter="smoke"), task_prompt="t",
        system_prompt="s", model="m", output_dir=Path("/tmp/o"),
        conditions=[Condition(name="baseline"), Condition(name="rcc", orchestration="rcc")])
    with pytest.raises(ValueError, match="does not support orchestration"):
        _validate(exp)
    # A plain benchmark experiment still loads.
    exp.conditions = [Condition(name="baseline")]
    _validate(exp)
