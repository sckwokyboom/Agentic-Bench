import json
from pathlib import Path

from abench.bench.run import run_benchmark, _safe_instance_dirname
from abench.config import BenchmarkCfg, Condition, Experiment, MetricsCfg
from abench.metrics import MetricsConfig
from tests.fakes import FakeOpenCodeClient


def _mcfg() -> MetricsConfig:
    # Build the runtime metrics config exactly as run_experiment does
    # (runner.py: `MetricsConfig(**exp.metrics.model_dump())`).
    return MetricsConfig(**MetricsCfg().model_dump())


def _bench_exp(tmp_path: Path) -> Experiment:
    return Experiment(
        name="smoke-bench",
        benchmark=BenchmarkCfg(adapter="smoke"),
        task_prompt="(unused in benchmark mode)",
        system_prompt="be good",
        model="fake/model",
        output_dir=str(tmp_path / "runs"),
        repetitions=1,
        conditions=[Condition(name="baseline")],
    )


class _SolvingClient:
    """Writes the smoke fix into the workdir, then delegates to the known-good
    fake for a valid Trace."""
    def run_task(self, **kwargs):
        Path(kwargs["workdir"], "calc.py").write_text("def add(a, b):\n    return a + b\n")
        return FakeOpenCodeClient().run_task(**kwargs)


class _RaisingClient:
    def run_task(self, **kwargs):
        raise RuntimeError("boom")


def test_safe_instance_dirname():
    assert _safe_instance_dirname("apache__dubbo-10638") == "apache__dubbo-10638"
    assert _safe_instance_dirname("PA19/Cell.java") == "PA19_Cell.java"


def test_run_benchmark_solved(tmp_path: Path):
    exp = _bench_exp(tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    run_benchmark(exp, _SolvingClient(), _mcfg(), {}, root)

    rundir = root / "smoke-1" / "baseline" / "rep_0"
    assert (rundir / "events.jsonl").read_text().strip() != ""
    assert (rundir / "trace.json").exists()
    assert (rundir / "changes.patch").exists()

    grade = json.loads((rundir / "grade.json").read_text())
    assert grade["resolved"] is True
    assert grade["evaluator"] == "smoke@1"
    assert grade["standard_protocol"] is True

    metrics = json.loads((rundir / "metrics.json").read_text())
    assert metrics["success"] is True
    assert metrics["benchmark"]["instance_id"] == "smoke-1"
    assert metrics["benchmark"]["official"]["resolved"] is True


def test_run_benchmark_unsolved(tmp_path: Path):
    exp = _bench_exp(tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    # Plain fake never fixes calc.py, so the smoke grade fails.
    run_benchmark(exp, FakeOpenCodeClient(), _mcfg(), {}, root)

    rundir = root / "smoke-1" / "baseline" / "rep_0"
    grade = json.loads((rundir / "grade.json").read_text())
    assert grade["resolved"] is False
    metrics = json.loads((rundir / "metrics.json").read_text())
    assert metrics["success"] is False


def test_run_benchmark_records_error_and_continues(tmp_path: Path):
    exp = _bench_exp(tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    run_benchmark(exp, _RaisingClient(), _mcfg(), {}, root)  # must NOT raise
    rundir = root / "smoke-1" / "baseline" / "rep_0"
    assert (rundir / "error.log").exists()
    assert "boom" in (rundir / "error.log").read_text()


def test_run_benchmark_cleans_up_workdirs(tmp_path: Path):
    import glob
    import os
    import tempfile as _tmp
    pat = os.path.join(_tmp.gettempdir(), "abench-bench-*")
    before = set(glob.glob(pat))
    exp = _bench_exp(tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    run_benchmark(exp, _SolvingClient(), _mcfg(), {}, root)
    after = set(glob.glob(pat))
    assert after <= before  # no leaked per-run tempdir


def test_run_benchmark_writes_summary(tmp_path: Path):
    exp = _bench_exp(tmp_path)
    root = tmp_path / "root"; root.mkdir()
    run_benchmark(exp, _SolvingClient(), _mcfg(), {}, root)

    summary = json.loads((root / "benchmark_summary.json").read_text())
    assert summary["adapter"] == "smoke"
    assert summary["n_runs"] == 1
    assert summary["n_errors"] == 0
    assert summary["resolved_rate"] == 1.0
    assert summary["runs"][0]["instance_id"] == "smoke-1"
    assert summary["runs"][0]["condition"] == "baseline"
    assert summary["runs"][0]["resolved"] is True


def test_run_benchmark_summary_records_errors(tmp_path: Path):
    exp = _bench_exp(tmp_path)
    root = tmp_path / "root"; root.mkdir()
    run_benchmark(exp, _RaisingClient(), _mcfg(), {}, root)

    summary = json.loads((root / "benchmark_summary.json").read_text())
    assert summary["n_runs"] == 1
    assert summary["n_errors"] == 1
    assert summary["resolved_rate"] == 0.0          # no scored runs
    assert summary["runs"][0]["resolved"] is None
    assert "error" in summary["runs"][0]
