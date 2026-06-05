"""Offline metric recompute from stored trace.json (no agent re-run)."""
import json
from pathlib import Path

from abench.metrics import MetricsConfig
from abench.recompute import recompute_run, recompute_batch
from abench.trace_model import Step, StepKind, Trace, TurnInfo


def _mcfg() -> MetricsConfig:
    return MetricsConfig(
        test_command_patterns=[r"gradlew?.*test"],
        shell_tool_names=["bash"], read_tool_names=["read"],
        search_tool_names=["grep"], command_arg_keys=["command"],
    )


def _write_run(rundir: Path, trace: Trace, patch: str = "") -> None:
    rundir.mkdir(parents=True, exist_ok=True)
    (rundir / "trace.json").write_text(json.dumps(trace.to_dict(), indent=2))
    (rundir / "changes.patch").write_text(patch)
    (rundir / "metrics.json").write_text("{}")  # stale; recompute overwrites


def test_recompute_fills_tokens_and_sums_gradle_multimodule(tmp_path):
    """tokens_in/out backfilled from per-turn data (export gave no totals), and
    tests_executed sums all gradle module summary lines."""
    trace = Trace(
        steps=[
            Step(kind=StepKind.TOOL_CALL, tool_name="bash", tool_call_id="c1",
                 tool_args={"command": "cd /repo && ./gradlew test"}),
            Step(kind=StepKind.TOOL_RESULT, tool_call_id="c1",
                 output="263 tests completed, 0 failed\n89 tests completed, 0 failed"),
        ],
        turns=[TurnInfo(message_id="M0", tokens_in=100, tokens_out=20,
                        tokens_reasoning=5, cost=0.01)],
        tokens_in=None, tokens_out=None,  # export reported nothing
        verify_status="passed", verify_passed_count=352,
    )
    rundir = tmp_path / "baseline" / "rep_0"
    _write_run(rundir, trace)

    m = recompute_run(rundir, _mcfg())
    assert m is not None
    assert m["n_test_runs"] == 1
    assert m["n_tests_executed"] == 352          # 263 + 89, both modules summed
    assert m["tokens_in"] == 100 and m["tokens_out"] == 20  # from per-turn fallback
    assert m["verify_status"] == "passed"        # preserved
    # metrics.json + trace.json rewritten
    assert json.loads((rundir / "metrics.json").read_text())["tokens_in"] == 100
    assert json.loads((rundir / "trace.json").read_text())["tokens_in"] == 100


def test_recompute_keeps_existing_totals_when_present(tmp_path):
    """If the trace already has token totals (export had usage), they're kept."""
    trace = Trace(turns=[TurnInfo(message_id="M0", tokens_in=1)],
                  tokens_in=999, tokens_out=888)
    rundir = tmp_path / "baseline" / "rep_0"
    _write_run(rundir, trace)
    m = recompute_run(rundir, _mcfg())
    assert m["tokens_in"] == 999 and m["tokens_out"] == 888


def test_recompute_run_none_without_trace(tmp_path):
    (tmp_path / "baseline" / "rep_0").mkdir(parents=True)
    assert recompute_run(tmp_path / "baseline" / "rep_0", _mcfg()) is None


def test_recompute_batch_counts_all_reps(tmp_path):
    for cond in ("baseline", "augmented"):
        for rep in range(2):
            _write_run(tmp_path / cond / f"rep_{rep}",
                       Trace(turns=[], tokens_in=1, tokens_out=1))
    assert recompute_batch(tmp_path, _mcfg()) == 4
