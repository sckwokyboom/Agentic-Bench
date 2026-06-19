"""Redaction core for share-safe trace export (shared by the CLI and the Web UI).

Allowlist model: a safe trace is built by copying ONLY a fixed set of known-safe
fields (tool calls, scrubbed args, the agent's diffs and text, relative timings,
numeric verify facts). Anything not on the allowlist — ids, session/message
handles, raw provider/proxy error text, the isolation nonce, the raw session
export, env — is never read, so new trace fields are dropped by default, not
leaked. Every kept string is additionally scrubbed of URLs/emails/IPs/tokens and
home/temp/workdir roots. Raw tool OUTPUTS are excluded unless explicitly opted in
(and then scrubbed AND truncated).
"""
from __future__ import annotations

import re
from collections import Counter

from .tokens import estimate_tokens

SCHEMA = "abench-safe-trace/v1"

# Ordered scrubbers — URLs before paths (URLs contain '//'); secrets before hex.
_SCRUBBERS: list[tuple[str, re.Pattern, str]] = [
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "<email>"),
    ("url", re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s'\"<>)\]]+", re.I), "<url>"),
    ("secret", re.compile(
        r"\b(?:sk-[A-Za-z0-9]{6,}|gh[pousr]_[A-Za-z0-9]{6,}|xox[baprs]-[A-Za-z0-9-]{6,})\b"),
        "<secret>"),
    ("secret", re.compile(
        r"(?i)\b(?:bearer|authorization|api[_-]?key|token|secret|password|passwd)\b"
        r"\s*[:=]?\s*[^\s'\"]+"),
        "<secret>"),
    ("ip", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b"), "<ip>"),
    ("hex", re.compile(r"\b[0-9a-fA-F]{24,}\b"), "<hex>"),
    ("tmp", re.compile(r"(?:/private)?/var/folders/[A-Za-z0-9_+/-]+?/T/?"), "<tmp>/"),
    ("workdir", re.compile(r"\babench-[A-Za-z0-9._-]+"), "abench-<id>"),
    ("home", re.compile(r"/(?:Users|home)/[^/\s'\"]+"), "~"),
    ("home", re.compile(r"[A-Za-z]:\\Users\\[^\\\s'\"]+"), "~"),
]


class Scrubber:
    """Masks sensitive substrings; tallies hits per category for the report."""

    def __init__(self, strip_prefix: str | None = None):
        self.counts: Counter = Counter()
        self._strip = strip_prefix.rstrip("/") if strip_prefix else None

    def text(self, s):
        if not isinstance(s, str) or not s:
            return s
        if self._strip:
            n = s.count(self._strip)
            if n:
                s = s.replace(self._strip + "/", "").replace(self._strip, "")
                self.counts["strip_prefix"] += n
        for cat, rx, repl in _SCRUBBERS:
            s, n = rx.subn(repl, s)
            if n:
                self.counts[cat] += n
        return s

    def obj(self, o):
        """Recursively scrub strings in dicts/lists; keep keys and non-strings."""
        if isinstance(o, str):
            return self.text(o)
        if isinstance(o, dict):
            return {k: self.obj(v) for k, v in o.items()}
        if isinstance(o, list):
            return [self.obj(v) for v in o]
        return o


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


_DIGEST_TEXT_CHARS = 160
_DIGEST_ARG_CHARS = 200


def _truncate_strings(o, limit: int):
    if isinstance(o, str):
        return o if len(o) <= limit else o[:limit] + "…"
    if isinstance(o, dict):
        return {k: _truncate_strings(v, limit) for k, v in o.items()}
    if isinstance(o, list):
        return [_truncate_strings(v, limit) for v in o]
    return o


def _diffstat(patch: str) -> dict:
    """Added/removed line counts from a unified diff (ignoring the ± file headers)."""
    added = removed = 0
    for ln in patch.splitlines():
        if ln.startswith("+++") or ln.startswith("---"):
            continue
        if ln.startswith("+"):
            added += 1
        elif ln.startswith("-"):
            removed += 1
    return {"added": added, "removed": removed}


def safe_step(step: dict, base_ts, scr: Scrubber, *, include_outputs: bool,
              max_output_chars: int, digest: bool = False) -> dict:
    """Project ONE step to allowlisted, scrubbed fields. In ``digest`` mode the
    bulky bodies are dropped — diffs become +/- line counts, the agent's text is
    truncated, long args clipped — leaving a compact navigation skeleton."""
    out: dict = {"kind": step.get("kind")}
    turn = step.get("turn")
    if turn is not None:
        out["turn"] = turn
    ts = _num(step.get("ts"))
    if ts is not None and base_ts is not None:
        out["t"] = round(ts - base_ts, 1)  # relative offset only, never wall-clock
    if step.get("tool_name"):
        out["tool"] = scr.text(step["tool_name"])
    if isinstance(step.get("tool_args"), (dict, list)):
        a = scr.obj(step["tool_args"])
        out["args"] = _truncate_strings(a, _DIGEST_ARG_CHARS) if digest else a
    if step.get("path"):
        out["path"] = scr.text(step["path"])
    if step.get("patch"):
        if digest:
            out["edit"] = _diffstat(step["patch"])  # +/- counts, not the body
        else:
            out["patch"] = scr.text(step["patch"])
    if step.get("text"):
        t = scr.text(step["text"])
        out["text"] = (t[:_DIGEST_TEXT_CHARS] + "…") if (
            digest and isinstance(t, str) and len(t) > _DIGEST_TEXT_CHARS) else t
    ec = step.get("exit_code")
    if ec is not None:
        out["exit_code"] = ec
    if step.get("output"):
        # Always carry the observation's token COST (a safe number), even when the
        # raw output text is excluded — that's the "context noise" signal.
        out["obs_tokens"] = estimate_tokens(str(step["output"]))
        if include_outputs:
            raw = str(step["output"])
            clipped = raw[:max_output_chars]
            out["output"] = scr.text(clipped) + ("…[truncated]" if len(raw) > max_output_chars else "")
    return out


def safe_trace(trace: dict, manifest: dict, scr: Scrubber, *,
               include_outputs: bool, max_output_chars: int, digest: bool = False) -> dict:
    """Project ONE trace dict (+ {condition, rep}) to its allowlisted, scrubbed form."""
    base_ts = _num(trace.get("started_at"))
    steps = [safe_step(s, base_ts, scr, include_outputs=include_outputs,
                       max_output_chars=max_output_chars, digest=digest)
             for s in (trace.get("steps") or []) if isinstance(s, dict)]

    by_name: Counter = Counter()
    for s in steps:
        if s.get("kind") == "tool_call" and s.get("tool"):
            by_name[s["tool"]] += 1

    # Observation token cost per tool, from the RAW steps (the projected steps
    # drop tool_call_id, so attribute results to their calling tool here).
    name_by_call = {s.get("tool_call_id"): s.get("tool_name")
                    for s in (trace.get("steps") or [])
                    if isinstance(s, dict) and s.get("kind") == "tool_call" and s.get("tool_call_id")}
    obs_total = 0
    obs_by_tool: dict[str, int] = {}
    for s in (trace.get("steps") or []):
        if isinstance(s, dict) and s.get("kind") == "tool_result" and s.get("output"):
            est = estimate_tokens(str(s["output"]))
            obs_total += est
            nm = name_by_call.get(s.get("tool_call_id")) or "?"
            obs_by_tool[nm] = obs_by_tool.get(nm, 0) + est

    ended = _num(trace.get("ended_at"))
    duration = round(ended - base_ts, 1) if base_ts is not None and ended is not None else None

    return {
        "condition": manifest.get("condition"),
        "rep": manifest.get("rep"),
        "duration_s": duration,
        "n_steps": len(steps),
        "n_tool_calls": sum(by_name.values()),
        "tool_calls_by_name": dict(by_name),
        "obs_tokens_total": obs_total,
        "obs_tokens_by_tool": obs_by_tool,
        "finished": trace.get("finished"),
        "interrupted_reason": scr.text(trace.get("interrupted_reason")),
        # First-class "stuck" outcome: the run was killed by the loop watchdog
        # (agent repeated the same step with no progress). A label on the
        # outcome only — never a change to the run itself.
        "stuck": trace.get("interrupted_reason") == "looping",
        # Why the model's last turn ended + whether it actually touched source —
        # so a run that "finished" but trailed off (stop_reason="stop", no edits)
        # is distinguishable from a real attempt that failed tests.
        "stop_reason": scr.text(
            next((t.get("reason") for t in reversed(trace.get("turns") or [])
                  if isinstance(t, dict) and t.get("reason")),
                 trace.get("stop_reason"))),
        "made_source_changes": bool((trace.get("final_diff_summary") or {}).get("files")),
        "n_service_errors": _num(trace.get("n_service_errors")) or 0,
        "n_rate_limits": _num(trace.get("n_rate_limits")) or 0,
        "tokens_in": _num(trace.get("tokens_in")),
        "tokens_out": _num(trace.get("tokens_out")),
        "tokens_reasoning": _num(trace.get("tokens_reasoning")),
        "target_similarity": _num(trace.get("target_similarity")),
        "verify": {
            "status": trace.get("verify_status"),
            "reason": trace.get("verify_reason"),
            "message": scr.text(trace.get("verify_message")),
            "command": scr.text(trace.get("verify_command")),
            "passed_count": _num(trace.get("verify_passed_count")),
            "failed_count": _num(trace.get("verify_failed_count")),
            "expected_total": _num(trace.get("verify_expected_total")),
            "failed_names": [scr.text(n) for n in (trace.get("verify_failed_names") or [])][:20],
        },
        "steps": steps,
    }


def build_bundle(items, *, include_outputs: bool = False, max_output_chars: int = 500,
                 strip_prefix: str | None = None, digest: bool = False) -> dict:
    """Bundle a list of (trace_dict, manifest_dict) into one safe artifact.

    A single shared Scrubber tallies redactions across all traces. ``digest``
    drops bulky bodies (diff bodies → +/- counts, text truncated) for a compact,
    pasteable navigation skeleton."""
    scr = Scrubber(strip_prefix)
    traces = [safe_trace(t, m or {}, scr, include_outputs=include_outputs,
                         max_output_chars=max_output_chars, digest=digest)
              for t, m in items]
    return {
        "schema": SCHEMA,
        "policy": ("allowlist; " + ("digest; " if digest else "")
                   + "outputs " + ("included(scrubbed+truncated)" if include_outputs
                                   else "excluded")),
        "n_traces": len(traces),
        "redaction": dict(scr.counts),
        "traces": traces,
    }
