"""Merge per-phase opencode Traces + controller steps into one stitched Trace,
so a phased run produces the same schema/metrics as the baseline (single-run)
trace. Token/cost are summed across phases (LLM-only). Steps are phase-tagged
and ordered by timestamp; controller steps interleave by their own ts.
"""
from __future__ import annotations

from .trace_model import Step, StepKind, Trace, TurnInfo


def _sum(values: list[int | float | None]) -> int | float | None:
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def stitch(
    phases: list[tuple[str, Trace]],
    controller_steps: list[Step],
    *,
    outcome: str | None = None,
    controller_test_runs: int = 0,
    controller_test_time_s: float | None = None,
    accepted_rounds: int = 0,
    reverted_rounds: int = 0,
) -> Trace:
    steps: list[Step] = []
    turns: list[TurnInfo] = []
    for label, tr in phases:
        for s in tr.steps:
            s.phase = label                 # tag with the phase it came from
            steps.append(s)
        turns.extend(tr.turns)
    steps.extend(controller_steps)
    steps.sort(key=lambda s: (s.ts if s.ts is not None else 0.0))

    # Re-number turns to be globally unique + ordered. Each per-phase opencode
    # session restarts turn indices at 0, so without this the phases would
    # collide in any turn-grouped view (phase-A turn 0 + phase-B turn 0 → one
    # card). Group by (phase, message_id); CONTROLLER / message_id-less steps are
    # each their own turn. TurnInfo still joins by message_id (unchanged, unique
    # per session), so per-turn stats land correctly.
    turn_of: dict[tuple, int] = {}
    nxt = 0
    for s in steps:
        if s.kind == StepKind.CONTROLLER or s.message_id is None:
            s.turn = nxt
            nxt += 1
        else:
            key = (s.phase, s.message_id)
            if key not in turn_of:
                turn_of[key] = nxt
                nxt += 1
            s.turn = turn_of[key]

    starts = [tr.started_at for _, tr in phases if tr.started_at is not None]
    ends = [tr.ended_at for _, tr in phases if tr.ended_at is not None]
    return Trace(
        steps=steps,
        turns=turns,
        started_at=min(starts) if starts else None,
        ended_at=max(ends) if ends else None,
        tokens_in=_sum([tr.tokens_in for _, tr in phases]),
        tokens_out=_sum([tr.tokens_out for _, tr in phases]),
        cost=_sum([tr.cost for _, tr in phases]),
        tokens_reasoning=_sum([tr.tokens_reasoning for _, tr in phases]),
        orchestration_outcome=outcome,
        controller_test_runs=controller_test_runs,
        controller_test_time_s=controller_test_time_s,
        accepted_rounds=accepted_rounds,
        reverted_rounds=reverted_rounds,
    )
