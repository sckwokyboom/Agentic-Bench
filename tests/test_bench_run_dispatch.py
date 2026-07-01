import json
from pathlib import Path

from abench.config import BenchmarkCfg, Condition, Experiment
from abench.runner import run_experiment
from tests.fakes import FakeOpenCodeClient


class _SolvingClient:
    def run_task(self, **kwargs):
        Path(kwargs["workdir"], "calc.py").write_text("def add(a, b):\n    return a + b\n")
        return FakeOpenCodeClient().run_task(**kwargs)


def test_run_experiment_dispatches_to_benchmark(tmp_path: Path):
    exp = Experiment(
        name="smoke-bench",
        benchmark=BenchmarkCfg(adapter="smoke"),
        task_prompt="(unused)",
        system_prompt="be good",
        model="fake/model",
        output_dir=str(tmp_path / "runs"),
        repetitions=2,
        conditions=[Condition(name="baseline")],
    )
    root = run_experiment(exp, lambda e: _SolvingClient())

    for rep in range(2):
        rundir = root / "smoke-1" / "baseline" / f"rep_{rep}"
        metrics = json.loads((rundir / "metrics.json").read_text())
        assert metrics["success"] is True
        assert metrics["benchmark"]["official"]["resolved"] is True
