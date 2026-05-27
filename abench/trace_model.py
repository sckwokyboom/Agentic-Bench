from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class StepKind(str, Enum):
    ASSISTANT_TEXT = "assistant_text"
    REASONING = "reasoning"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    FILE_EDIT = "file_edit"


@dataclass
class Step:
    kind: StepKind
    ts: float | None = None
    turn: int | None = None
    text: str | None = None
    tool_name: str | None = None
    tool_args: dict | None = None
    tool_call_id: str | None = None
    output: str | None = None
    exit_code: int | None = None
    path: str | None = None
    patch: str | None = None


@dataclass
class Trace:
    steps: list[Step] = field(default_factory=list)
    started_at: float | None = None
    ended_at: float | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost: float | None = None
    finished: bool = False
    interrupted_reason: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        for step in d["steps"]:
            kind = step["kind"]
            step["kind"] = kind.value if isinstance(kind, StepKind) else kind
        return d


def trace_from_dict(d: dict) -> Trace:
    steps = [
        Step(kind=StepKind(s["kind"]), **{k: v for k, v in s.items() if k != "kind"})
        for s in d.get("steps", [])
    ]
    return Trace(steps=steps, **{k: v for k, v in d.items() if k != "steps"})
