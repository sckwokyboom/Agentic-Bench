import json
from abench.trace_model import Step, StepKind, Trace, TurnInfo, trace_from_dict
from abench.trace_stitch import stitch


def _phase_trace(text, ts, tin, tout):
    return Trace(
        started_at=ts, ended_at=ts + 1,
        tokens_in=tin, tokens_out=tout,
        turns=[TurnInfo(message_id="m", reason="stop", tokens_in=tin, tokens_out=tout)],
        steps=[Step(kind=StepKind.ASSISTANT_TEXT, ts=ts, turn=0, text=text)],
    )


def test_stitch_concatenates_tags_and_sums():
    phases = [("understand", _phase_trace("read", 100.0, 10, 1)),
              ("implement", _phase_trace("edit", 200.0, 20, 2))]
    controller = [Step(kind=StepKind.CONTROLLER, ts=150.0, turn=0,
                       text="ran suite -> 4 failures", phase="implement")]
    t = stitch(phases, controller, outcome="green",
               controller_test_runs=1, controller_test_time_s=3.0,
               accepted_rounds=1, reverted_rounds=0)
    # round-trips through json
    t = trace_from_dict(json.loads(json.dumps(t.to_dict())))
    # steps ordered by ts, phase-tagged, controller step interleaved
    kinds = [(s.kind, s.phase) for s in t.steps]
    assert kinds == [(StepKind.ASSISTANT_TEXT, "understand"),
                     (StepKind.CONTROLLER, "implement"),
                     (StepKind.ASSISTANT_TEXT, "implement")]
    assert t.tokens_in == 30 and t.tokens_out == 3
    assert t.started_at == 100.0 and t.ended_at == 201.0
    assert t.orchestration_outcome == "green"
    assert t.controller_test_runs == 1 and t.accepted_rounds == 1
    assert len(t.turns) == 2
