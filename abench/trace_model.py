from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class StepKind(str, Enum):
    ASSISTANT_TEXT = "assistant_text"
    REASONING = "reasoning"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    FILE_EDIT = "file_edit"
    CONTROLLER = "controller"


@dataclass
class Step:
    kind: StepKind
    ts: float | None = None
    turn: int | None = None
    message_id: str | None = None
    text: str | None = None
    tool_name: str | None = None
    tool_args: dict | None = None
    tool_call_id: str | None = None
    output: str | None = None
    exit_code: int | None = None
    path: str | None = None
    patch: str | None = None
    # Orchestration: the phase this step belongs to (None for the autonomous
    # baseline loop). CONTROLLER steps are deterministic controller actions.
    phase: str | None = None


@dataclass
class TurnInfo:
    message_id: str
    reason: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_reasoning: int | None = None
    cost: float | None = None
    started_at: float | None = None
    ended_at: float | None = None


@dataclass
class FileChange:
    path: str
    added: int = 0
    removed: int = 0


@dataclass
class FinalDiffSummary:
    files: list[FileChange] = field(default_factory=list)
    total_added: int = 0
    total_removed: int = 0


@dataclass
class Trace:
    steps: list[Step] = field(default_factory=list)
    started_at: float | None = None
    ended_at: float | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost: float | None = None
    tokens_reasoning: int | None = None
    cache_read: int | None = None
    cache_write: int | None = None

    # The model + provider that ACTUALLY served the run, read from the opencode
    # session export (info.model = {id, providerID}). Ground truth: the configured
    # experiment model can be overridden at runtime (a server-side YAML, an
    # opencode default), so this records what really ran rather than what was
    # requested. Falls back to the configured model when the session export
    # didn't echo one (some OpenAI-compatible endpoints don't).
    model: str | None = None
    provider: str | None = None

    finished: bool = False
    interrupted_reason: str | None = None
    # Why the model's final turn ended (opencode/AI-SDK finish reason of the last
    # step-finish): "stop" (ended its turn — often no tool call → loop ends),
    # "length" (truncated), "tool-calls", "error", "aborted"… Lets a run that
    # "finished" cleanly still reveal WHY it stopped (e.g. trailed off mid-task).
    stop_reason: str | None = None

    turns: list[TurnInfo] = field(default_factory=list)

    verify_status: str | None = None
    verify_reason: str | None = None
    verify_message: str | None = None
    verify_command: str | None = None
    verify_duration_s: float | None = None
    verify_passed_count: int | None = None
    verify_failed_count: int | None = None
    verify_failed_names: list[str] = field(default_factory=list)
    verify_baseline_unknown: bool = False
    verify_insensitive: bool = False
    # Full expected suite size — the reference (gold) verify's passing count from
    # the baseline cache. Used as the tests_pass_rate denominator so tests that
    # never ran (an early abort, or a module that didn't compile) count as
    # not-passed instead of being silently dropped. None when unknown.
    verify_expected_total: int | None = None

    # Service/proxy errors surfaced by opencode (rate limits, 5xx, etc.).
    n_service_errors: int = 0
    n_rate_limits: int = 0
    service_error_messages: list[str] = field(default_factory=list)

    final_diff_summary: FinalDiffSummary | None = None

    isolation_nonce: str | None = None

    # Max difflib similarity of a target method's final body to the reference
    # original (0..1), or None if not computed/comparable. Drives the cheating
    # detector's 'output ≈ original' signal.
    target_similarity: float | None = None

    # Phased-orchestration outcome + controller overhead (None/0 for the
    # autonomous baseline). outcome ∈ {green, budget, stuck, compile-fail}.
    orchestration_outcome: str | None = None
    controller_test_runs: int = 0
    controller_test_time_s: float | None = None
    accepted_rounds: int = 0
    reverted_rounds: int = 0

    # v2 timing breakdown — placeholder fields, populated in Phase 2
    llm_latency_s: float | None = None
    tool_exec_s: float | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        for step in d["steps"]:
            kind = step["kind"]
            step["kind"] = kind.value if isinstance(kind, StepKind) else kind
        return d


def trace_from_dict(d: dict) -> Trace:
    steps = [Step(kind=StepKind(s["kind"]),
                  **{k: v for k, v in s.items() if k != "kind"})
             for s in d.get("steps", [])]
    turns_raw = d.get("turns", [])
    turns = [TurnInfo(**t) for t in turns_raw]
    fds_raw = d.get("final_diff_summary")
    if fds_raw is not None:
        fds = FinalDiffSummary(
            files=[FileChange(**fc) for fc in fds_raw.get("files", [])],
            total_added=fds_raw.get("total_added", 0),
            total_removed=fds_raw.get("total_removed", 0),
        )
    else:
        fds = None
    remaining = {k: v for k, v in d.items()
                 if k not in {"steps", "turns", "final_diff_summary"}}
    return Trace(steps=steps, turns=turns, final_diff_summary=fds, **remaining)
