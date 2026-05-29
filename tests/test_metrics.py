# tests/test_metrics.py
from abench.metrics import MetricsConfig, extract
from abench.trace_model import Step, StepKind, Trace


def _cfg():
    return MetricsConfig(
        test_command_patterns=["pytest", r"(npm|pnpm|yarn)( run)? test"],
        shell_tool_names=["bash"],
        read_tool_names=["read"],
        search_tool_names=["grep", "glob", "list"],
        command_arg_keys=["command", "cmd"],
    )


def _trace():
    return Trace(
        started_at=0.0,
        ended_at=12.0,
        tokens_in=100,
        tokens_out=200,
        finished=True,
        steps=[
            Step(kind=StepKind.ASSISTANT_TEXT, ts=0.0, turn=0, text="plan"),
            Step(kind=StepKind.TOOL_CALL, ts=1.0, turn=0,
                 tool_name="read", tool_args={"path": "a.py"}),
            Step(kind=StepKind.TOOL_CALL, ts=2.0, turn=0,
                 tool_name="grep", tool_args={"pattern": "foo"}),
            Step(kind=StepKind.ASSISTANT_TEXT, ts=3.0, turn=1, text="editing"),
            Step(kind=StepKind.FILE_EDIT, ts=4.0, turn=1, path="a.py", patch="x"),
            Step(kind=StepKind.TOOL_CALL, ts=5.0, turn=2,
                 tool_name="bash", tool_args={"command": "pytest -q"}),
            Step(kind=StepKind.TOOL_CALL, ts=6.0, turn=2,
                 tool_name="bash", tool_args={"command": "ls -la"}),
        ],
    )


def test_extract_counts_metrics():
    patch = (
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
        "@@ -0,0 +1,1 @@\n+added line\n"
    )
    m = extract(_trace(), patch, _cfg())
    assert m["n_steps"] == 3          # turns 0,1,2
    assert m["n_tool_calls"] == 4
    assert m["tool_calls_by_name"] == {"read": 1, "grep": 1, "bash": 2}
    assert m["n_test_runs"] == 1      # only "pytest -q" matches
    assert m["n_reads"] == 1
    assert m["n_searches"] == 1
    assert m["n_files_edited"] == 1
    assert m["diff_lines_added"] == 1
    assert m["duration_s"] == 12.0
    assert m["time_to_first_edit_s"] == 4.0
    assert m["finished"] is True
    assert m["success"] is None


def test_extract_copies_verify_fields_and_auto_success_passed():
    cfg = _cfg()
    trace = Trace(
        started_at=0.0, ended_at=10.0,
        finished=True,
        verify_status="passed",
        verify_command="./gradlew test",
        verify_duration_s=12.0,
        verify_passed_count=142,
        verify_failed_count=0,
        steps=[],
    )
    m = extract(trace, "", cfg)
    assert m["verify_status"] == "passed"
    assert m["verify_passed_count"] == 142
    assert m["success"] is True


def test_extract_auto_success_failed():
    cfg = _cfg()
    trace = Trace(
        started_at=0.0, ended_at=10.0,
        finished=True,
        verify_status="failed",
        verify_failed_count=3,
        steps=[],
    )
    m = extract(trace, "", cfg)
    assert m["success"] is False


def test_extract_auto_success_none_when_skipped():
    cfg = _cfg()
    trace = Trace(
        started_at=0.0, ended_at=10.0,
        finished=True,
        verify_status="skipped",
        steps=[],
    )
    m = extract(trace, "", cfg)
    assert m["success"] is None
