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
                 timeout_s, on_event, log_sink=None, cancel_event=None):
        self.workdir = workdir
        raise RuntimeError("boom")


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
