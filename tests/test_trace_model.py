import json
from abench.trace_model import Step, StepKind, Trace, trace_from_dict


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
