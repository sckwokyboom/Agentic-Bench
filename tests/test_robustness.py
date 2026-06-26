import json
from pathlib import Path

import pytest

from abench.config import Condition, Experiment, MetricsCfg, OpenCodeCfg
from abench.metrics import MetricsConfig, extract
from abench.runner import run_experiment
from abench.trace_model import Step, StepKind, Trace


def test_extract_skips_tool_call_with_no_name():
    cfg = MetricsConfig(
        test_command_patterns=["pytest"], shell_tool_names=["bash"],
        read_tool_names=["read"], search_tool_names=["grep"],
        command_arg_keys=["command"],
    )
    trace = Trace(started_at=0.0, ended_at=1.0, steps=[
        Step(kind=StepKind.TOOL_CALL, ts=0.4, turn=0, tool_name=None, tool_args={}),
        Step(kind=StepKind.TOOL_CALL, ts=0.5, turn=0, tool_name="bash",
             tool_args={"command": "ls"}),
    ])
    m = extract(trace, "", cfg)
    assert m["n_tool_calls"] == 2
    assert m["tool_calls_by_name"] == {"bash": 1}
    assert None not in m["tool_calls_by_name"]
    json.dumps(m)  # a None dict key would raise here


class _RaisingClient:
    def __init__(self):
        self.workdir = None

    def run_task(self, *, workdir, system_prompt, model, user_message,
                 timeout_s, agent_tools=None, on_event, log_sink=None, debug_sink=None, cancel_event=None):
        self.workdir = workdir
        raise RuntimeError("boom")


def test_cancel_saves_run_marked_truncated(tmp_path):
    """A cancel mid-run is kept as a FULL, analysable run: trace + metrics + diff are
    saved (verify runs on the partial diff), and it is flagged truncated via
    interrupted_reason='cancelled'."""
    import json
    import threading
    from abench.opencode_client import RunResult

    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "a.py").write_text("x = 1\n")
    (tmp_path / "reference").mkdir()
    ev = threading.Event()

    class _CancellingClient:
        def run_task(self, *, workdir, system_prompt, model, user_message, timeout_s,
                     agent_tools=None, on_event, log_sink=None, debug_sink=None,
                     cancel_event=None):
            ev.set()                       # user presses CANCEL mid-run
            return RunResult(trace=Trace(
                steps=[Step(kind=StepKind.ASSISTANT_TEXT, ts=1.0, turn=0, text="hi")],
                finished=True, interrupted_reason="cancelled"))

    exp = Experiment(
        name="exp1", fixture_path=fixture, reference_path=tmp_path / "reference",
        task_prompt="t", system_prompt="s", model="m",
        output_dir=tmp_path / "runs", repetitions=1,
        conditions=[Condition(name="baseline", augmentation=None)],
        opencode=OpenCodeCfg(), metrics=MetricsCfg(),
    )
    run_experiment(exp, lambda e: _CancellingClient(), cancel_event=ev)

    runs = list((tmp_path / "runs").glob("exp1/*/baseline/rep_0"))
    assert runs, "the cancelled run must still be saved as a full run"
    rd = runs[0]
    assert (rd / "trace.json").is_file() and (rd / "metrics.json").is_file()
    assert (rd / "changes.patch").is_file()       # the partial diff is captured
    tr = json.loads((rd / "trace.json").read_text())
    assert tr["interrupted_reason"] == "cancelled"   # flagged truncated for analysis


def test_workdir_cleaned_up_when_client_raises(tmp_path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "a.py").write_text("x = 1\n")
    (tmp_path / "reference").mkdir()
    exp = Experiment(
        name="exp1", fixture_path=fixture, reference_path=tmp_path / "reference",
        task_prompt="t", system_prompt="s", model="m",
        output_dir=tmp_path / "runs", repetitions=1,
        conditions=[Condition(name="baseline", augmentation=None)],
        opencode=OpenCodeCfg(), metrics=MetricsCfg(),
    )
    client = _RaisingClient()
    with pytest.raises(RuntimeError):
        run_experiment(exp, lambda e: client)
    assert client.workdir is not None
    assert not Path(client.workdir).exists()  # cleanup ran despite the error
