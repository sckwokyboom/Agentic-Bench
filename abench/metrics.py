# abench/metrics.py
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .cheating import detect_cheating
from .diffstat import parse_diffstat
from .tokens import estimate_tokens
from .trace_model import StepKind, Trace
from .verify import _parser_for


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
    edit_tool_names: list[str] = field(
        default_factory=lambda: ["edit", "write", "patch"])


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

    # Map tool_call_id → result output, to read each test command's output.
    result_output: dict[str, str] = {}
    for s in trace.steps:
        if s.kind == StepKind.TOOL_RESULT and s.tool_call_id is not None:
            result_output[s.tool_call_id] = s.output or ""

    # Observation (tool-result) token cost: a rough estimate of how much context
    # each tool's outputs add for the model to read, attributed to the calling
    # tool by tool_call_id. Estimate only (≈ chars/4) — for relative comparison
    # of context noise per tool, not exact provider tokenization.
    name_by_call = {s.tool_call_id: s.tool_name for s in tool_calls
                    if s.tool_call_id is not None}
    obs_tokens_by_tool: dict[str, int] = {}
    obs_tokens_total = 0
    for s in trace.steps:
        if s.kind == StepKind.TOOL_RESULT and s.output:
            est = estimate_tokens(s.output)
            obs_tokens_total += est
            name = name_by_call.get(s.tool_call_id or "", "?") or "?"
            obs_tokens_by_tool[name] = obs_tokens_by_tool.get(name, 0) + est

    # Tests executed: the TOTAL number of test-case executions across every test
    # run the agent did (passed + failed, summed). With the bench's "run all the
    # tests until they pass" instruction this is an effort/flailing proxy — an
    # agent that re-ran the whole suite many times spent more here. (The gradle
    # parser sums all per-module summary lines, so a multi-module run counts the
    # whole suite, not just the first module.)
    n_tests_executed = 0
    for s in tool_calls:
        if s.tool_name in cfg.shell_tool_names:
            cmd = _command_of(s, cfg.command_arg_keys)
            if any(r.search(cmd) for r in test_res):
                parser = _parser_for(cmd)
                out = result_output.get(s.tool_call_id or "", "")
                if parser is not None and out:
                    try:
                        passed, failed, _names = parser(out)
                        n_tests_executed += passed + failed
                    except ValueError:
                        pass

    n_reads = sum(1 for s in tool_calls if s.tool_name in cfg.read_tool_names)
    n_searches = sum(1 for s in tool_calls if s.tool_name in cfg.search_tool_names)

    # Exclude CONTROLLER + PHASE_PROMPT steps: the phased orchestrator records its
    # own actions (baseline suite, accept/revert, finalize) as CONTROLLER steps and
    # the exact LLM input per phase as PHASE_PROMPT steps, both for the FINISHED-view
    # visualization. Neither is the agent's own work — and stitch assigns them a
    # turn number — so counting them would inflate n_steps for phased vs autonomous
    # and corrupt the cross-condition comparison.
    _NON_AGENT = (StepKind.CONTROLLER, StepKind.PHASE_PROMPT)
    turns = {s.turn for s in trace.steps
             if s.turn is not None and s.kind not in _NON_AGENT}
    n_steps = len(turns)

    n_files, added, removed = parse_diffstat(patch_text)

    # First edit: FILE_EDIT steps exist only when the event stream carries
    # part.type=="patch" — opencode 1.15.x never emits those, so the edit tool
    # calls themselves are the primary signal. ts is truthy-filtered because
    # normalize() maps a missing state.time.start to 0.0, not None.
    ttfe = None
    edits = [s for s in trace.steps
             if s.kind == StepKind.FILE_EDIT and s.ts]
    edits += [s for s in tool_calls
              if s.tool_name in cfg.edit_tool_names and s.ts]
    if edits and trace.started_at is not None:
        ttfe = min(e.ts for e in edits) - trace.started_at

    duration = None
    if trace.started_at is not None and trace.ended_at is not None:
        duration = trace.ended_at - trace.started_at

    success = _success_from_status(trace.verify_status)

    # Fraction of tests passing at the end (passed / (passed+failed)). Captures
    # "2198/2200 passed" runs that a binary success=False would hide. None when
    # verify didn't produce counts.
    vp, vf = trace.verify_passed_count, trace.verify_failed_count
    # Only a genuine pass/fail verdict yields a rate; an 'invalid' (e.g. undercount)
    # or 'error' run is None, not a misleading near-zero from a partial count.
    if vp is not None and vf is not None and trace.verify_status in ("passed", "failed"):
        # Denominator is the full expected suite when known (reference verify),
        # so tests that never ran — an early abort, or a module that failed to
        # compile — count as not-passed rather than shrinking the denominator and
        # flattering a broken run to ~100%. Falls back to passed+failed.
        expected = trace.verify_expected_total
        denom = vp + vf
        if expected is not None and expected > denom:
            denom = expected
        tests_pass_rate = vp / denom if denom > 0 else None
    else:
        tests_pass_rate = None

    # How many tests actually executed (passed+failed) vs whether the build even
    # compiled — makes a verify UNDERCOUNT visible in the data (executed_total far
    # below the reference suite) instead of hiding behind a single pass/fail cell.
    executed_total = (
        vp + vf if (vp is not None and vf is not None) else None)
    compiled = None if executed_total is None else executed_total > 0

    return {
        "duration_s": duration,
        "n_steps": n_steps,
        "n_tool_calls": len(tool_calls),
        "tool_calls_by_name": by_name,
        "obs_tokens_total": obs_tokens_total,
        "obs_tokens_by_tool": obs_tokens_by_tool,
        "n_test_runs": n_test,
        "n_tests_executed": n_tests_executed,
        "n_reads": n_reads,
        "n_searches": n_searches,
        "n_files_edited": n_files,
        "diff_lines_added": added,
        "diff_lines_removed": removed,
        "tokens_in": trace.tokens_in,
        "tokens_out": trace.tokens_out,
        "tokens_reasoning": trace.tokens_reasoning,
        "cache_read": trace.cache_read,
        "cache_write": trace.cache_write,
        "cost": trace.cost,
        "temperature": trace.temperature,
        "time_to_first_edit_s": ttfe,
        "finished": trace.finished,
        "interrupted_reason": trace.interrupted_reason,
        # First-class "stuck" label: killed by the loop watchdog (repeated the
        # same step with no progress). Outcome label only, not a run change.
        "stuck": trace.interrupted_reason == "looping",
        "stop_reason": trace.stop_reason,
        "verify_status": trace.verify_status,
        "verify_command": trace.verify_command,
        "verify_duration_s": trace.verify_duration_s,
        "verify_passed_count": trace.verify_passed_count,
        "verify_failed_count": trace.verify_failed_count,
        "verify_expected_total": trace.verify_expected_total,
        "executed_total": executed_total,
        "compiled": compiled,
        "verify_failed_names": list(trace.verify_failed_names),
        "verify_reason": trace.verify_reason,
        "verify_message": trace.verify_message,
        "verify_baseline_unknown": trace.verify_baseline_unknown,
        "verify_insensitive": trace.verify_insensitive,
        "n_service_errors": trace.n_service_errors,
        "n_rate_limits": trace.n_rate_limits,
        "made_source_changes": bool(patch_text.strip()),
        "isolation_nonce": trace.isolation_nonce,
        "success": success,
        "tests_pass_rate": tests_pass_rate,
        # Advisory validity check: did the agent likely cheat? (network/git
        # history/outside-FS/broad-search from the trace + output≈original).
        "cheating": detect_cheating(trace, target_similarity=trace.target_similarity),
        # RapidCausalCoder telemetry (None/False/0 for non-rcc runs) — feeds APFDc
        # (root_rank), the hit-rate demo, and degrade-frequency analysis.
        "rcc_root_rank": trace.rcc_root_rank,
        "rcc_memory_hit": trace.rcc_memory_hit,
        "rcc_beta_degraded": trace.rcc_beta_degraded,
        "rcc_gamma_degraded": trace.rcc_gamma_degraded,
        "rcc_subset_test_runs": trace.rcc_subset_test_runs,
        "rcc_degraded": trace.rcc_degraded,
        "rcc_degrade_reason": trace.rcc_degrade_reason,
    }
