# abench/metrics.py
from __future__ import annotations

import re
from dataclasses import dataclass

from .diffstat import parse_diffstat
from .trace_model import StepKind, Trace


def _success_from_status(status: str | None) -> bool | None:
    """Single source for the success verdict: passed→True, failed→False, else None."""
    if status == "passed":
        return True
    if status == "failed":
        return False
    return None


@dataclass
class MetricsConfig:
    test_command_patterns: list[str]
    shell_tool_names: list[str]
    read_tool_names: list[str]
    search_tool_names: list[str]
    command_arg_keys: list[str]


def _command_of(step, keys: list[str]) -> str:
    args = step.tool_args or {}
    for key in keys:
        value = args.get(key)
        if isinstance(value, str):
            return value
    return ""


def extract(trace: Trace, patch_text: str, cfg: MetricsConfig) -> dict:
    tool_calls = [s for s in trace.steps if s.kind == StepKind.TOOL_CALL]

    by_name: dict[str, int] = {}
    for s in tool_calls:
        if s.tool_name is not None:
            by_name[s.tool_name] = by_name.get(s.tool_name, 0) + 1

    test_res = [re.compile(p) for p in cfg.test_command_patterns]
    n_test = 0
    for s in tool_calls:
        if s.tool_name in cfg.shell_tool_names:
            cmd = _command_of(s, cfg.command_arg_keys)
            if any(r.search(cmd) for r in test_res):
                n_test += 1

    n_reads = sum(1 for s in tool_calls if s.tool_name in cfg.read_tool_names)
    n_searches = sum(1 for s in tool_calls if s.tool_name in cfg.search_tool_names)

    turns = {s.turn for s in trace.steps if s.turn is not None}
    n_steps = len(turns)

    n_files, added, removed = parse_diffstat(patch_text)

    ttfe = None
    edits = [s for s in trace.steps
             if s.kind == StepKind.FILE_EDIT and s.ts is not None]
    if edits and trace.started_at is not None:
        ttfe = min(e.ts for e in edits) - trace.started_at

    duration = None
    if trace.started_at is not None and trace.ended_at is not None:
        duration = trace.ended_at - trace.started_at

    success = _success_from_status(trace.verify_status)

    return {
        "duration_s": duration,
        "n_steps": n_steps,
        "n_tool_calls": len(tool_calls),
        "tool_calls_by_name": by_name,
        "n_test_runs": n_test,
        "n_reads": n_reads,
        "n_searches": n_searches,
        "n_files_edited": n_files,
        "diff_lines_added": added,
        "diff_lines_removed": removed,
        "tokens_in": trace.tokens_in,
        "tokens_out": trace.tokens_out,
        "cost": trace.cost,
        "time_to_first_edit_s": ttfe,
        "finished": trace.finished,
        "interrupted_reason": trace.interrupted_reason,
        "verify_status": trace.verify_status,
        "verify_command": trace.verify_command,
        "verify_duration_s": trace.verify_duration_s,
        "verify_passed_count": trace.verify_passed_count,
        "verify_failed_count": trace.verify_failed_count,
        "verify_failed_names": list(trace.verify_failed_names),
        "verify_reason": trace.verify_reason,
        "verify_message": trace.verify_message,
        "verify_baseline_unknown": trace.verify_baseline_unknown,
        "isolation_nonce": trace.isolation_nonce,
        "success": success,
    }
