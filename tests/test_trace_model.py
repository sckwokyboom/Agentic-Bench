import json
from abench.trace_model import Step, StepKind, Trace, trace_from_dict


def test_trace_with_turn_info_and_verify_and_diff_roundtrips():
    from abench.trace_model import (
        FinalDiffSummary,
        FileChange,
        Trace,
        TurnInfo,
        trace_from_dict,
    )

    trace = Trace(
        finished=True,
        turns=[
            TurnInfo(
                message_id="msg_1",
                reason="tool-calls",
                tokens_in=3200,
                tokens_out=100,
                tokens_reasoning=80,
                cost=0.00024,
                started_at=100.0,
                ended_at=112.0,
            ),
            TurnInfo(
                message_id="msg_2",
                reason="stop",
                tokens_in=4100,
                tokens_out=600,
                tokens_reasoning=0,
                cost=0.00033,
                started_at=145.0,
                ended_at=163.0,
            ),
        ],
        verify_status="passed",
        verify_command="./gradlew test",
        verify_duration_s=84.0,
        verify_passed_count=142,
        verify_failed_count=0,
        verify_failed_names=[],
        verify_baseline_unknown=False,
        final_diff_summary=FinalDiffSummary(
            files=[FileChange(path="src/main/java/.../X.java", added=6, removed=1)],
            total_added=6,
            total_removed=1,
        ),
        isolation_nonce="abc123def456",
    )
    blob = json.dumps(trace.to_dict())
    restored = trace_from_dict(json.loads(blob))
    assert restored == trace
    assert restored.turns[0].reason == "tool-calls"
    assert restored.verify_passed_count == 142
    assert restored.final_diff_summary.total_added == 6
    assert restored.isolation_nonce == "abc123def456"


def test_trace_service_error_and_sensitivity_fields_roundtrip():
    trace = Trace(
        finished=False,
        interrupted_reason="rate_limit",
        n_service_errors=3,
        n_rate_limits=1,
        service_error_messages=["429 too many requests", "503 unavailable"],
        verify_insensitive=True,
    )
    blob = json.dumps(trace.to_dict())
    restored = trace_from_dict(json.loads(blob))
    assert restored == trace
    assert restored.n_service_errors == 3
    assert restored.n_rate_limits == 1
    assert restored.service_error_messages == ["429 too many requests", "503 unavailable"]
    assert restored.verify_insensitive is True


def test_trace_roundtrips_through_json():
    trace = Trace(
        started_at=100.0,
        ended_at=105.0,
        tokens_in=10,
        tokens_out=20,
        finished=True,
        steps=[
            Step(kind=StepKind.ASSISTANT_TEXT, ts=100.0, turn=0, text="thinking"),
            Step(kind=StepKind.TOOL_CALL, ts=101.0, turn=0,
                 tool_name="bash", tool_args={"command": "pytest"}, tool_call_id="c1"),
            Step(kind=StepKind.TOOL_RESULT, ts=102.0, turn=0,
                 tool_call_id="c1", output="ok", exit_code=0),
            Step(kind=StepKind.FILE_EDIT, ts=103.0, turn=1,
                 path="a.py", patch="@@ -1 +1 @@"),
        ],
    )
    blob = json.dumps(trace.to_dict())
    restored = trace_from_dict(json.loads(blob))
    assert restored == trace
    assert restored.steps[1].kind == StepKind.TOOL_CALL
    assert restored.steps[1].tool_args == {"command": "pytest"}
