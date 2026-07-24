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


def test_controller_logical_clock_rebased_into_wall_domain():
    # The real-run bug: agent phase steps carry wall-clock ts (epoch-scale) while
    # the orchestrator's controller steps carry a LOGICAL clock (1,2,3). A raw ts
    # sort then dumps every controller step to the front and the safe-trace export
    # renders huge-negative offsets. Stitch must re-time controllers into the agent
    # domain: baseline (pre-understand) just before t0, the rest just after their
    # tagged phase's agent work, preserving emission order.
    base = 1_000_000.0
    und = _phase_trace("understand-work", base + 20, 10, 5)          # agent ts base+20
    impl = Trace(started_at=base + 200, ended_at=base + 260,
                 steps=[Step(kind=StepKind.FILE_EDIT, ts=base + 250, turn=0,
                             message_id="b0", path="X", patch="+x")])
    ctrl = [  # logical clock 1,2,3 — a DISJOINT domain from the agent ts
        Step(kind=StepKind.CONTROLLER, ts=1.0, turn=0, text="baseline", phase="implement"),
        Step(kind=StepKind.CONTROLLER, ts=2.0, turn=0, text="contract", phase="understand"),
        Step(kind=StepKind.CONTROLLER, ts=3.0, turn=0, text="implement done", phase="implement"),
    ]
    t = stitch([("understand", und), ("implement", impl)], ctrl, outcome="green")
    started = t.started_at
    # no controller step is thrown out of the run's wall-clock window (the bug was
    # ts ≈ -1.7e9); allow a sub-second pre-roll for the pre-understand baseline
    csteps = [s for s in t.steps if s.kind == StepKind.CONTROLLER]
    assert all(started - 1.0 <= s.ts <= t.ended_at + 1.0 for s in csteps)
    # emission order preserved
    assert [s.text for s in csteps] == ["baseline", "contract", "implement done"]
    # baseline renders first (before the understand agent step), implement-done last
    assert t.steps[0].kind == StepKind.CONTROLLER and t.steps[0].text == "baseline"
    assert t.steps[-1].text == "implement done"


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


def test_stitch_renumbers_colliding_phase_turns():
    # Both phases' steps start at turn 0 (separate opencode sessions); after
    # stitching they must NOT collide, and same-message steps stay one turn.
    pa = Trace(started_at=100.0, ended_at=101.0, steps=[
        Step(kind=StepKind.TOOL_CALL, ts=100.0, turn=0, message_id="a0", tool_name="read"),
        Step(kind=StepKind.ASSISTANT_TEXT, ts=100.5, turn=0, message_id="a0", text="contract"),
    ])
    pb = Trace(started_at=200.0, ended_at=201.0, steps=[
        Step(kind=StepKind.FILE_EDIT, ts=200.0, turn=0, message_id="b0", path="X.java", patch="+x"),
    ])
    ctrl = [Step(kind=StepKind.CONTROLLER, ts=150.0, turn=0, text="ran suite", phase="implement")]
    t = stitch([("understand", pa), ("implement", pb)], ctrl, outcome="green")
    # 3 distinct logical turns: phase-A (msg a0, 2 steps share), phase-B (b0), controller
    assert len({s.turn for s in t.steps}) == 3
    assert len({s.turn for s in t.steps if s.message_id == "a0"}) == 1   # same-message = one turn
    ctrl_turn = next(s.turn for s in t.steps if s.kind == StepKind.CONTROLLER)
    assert ctrl_turn not in {s.turn for s in t.steps if s.kind != StepKind.CONTROLLER}
