#!/usr/bin/env python3
"""Export a REDACTED, share-safe view of an agent run's trace (standalone, stdlib-only).

Built to run on a locked-down / corporate machine and emit a file you can review
and hand off for trace analysis. It carries only what's needed to study the agent
loop — tool calls, their arguments, the diffs the agent produced, and the agent's
own text/reasoning — and nothing else.

SAFETY MODEL — allowlist, not denylist:
  The output is assembled by copying ONLY a fixed set of known-safe fields. Any
  field not on the allowlist (ids, session/message handles, raw provider/proxy
  error text, the isolation nonce, the raw opencode session export, env, etc.) is
  simply never read. New fields added to the trace in the future are dropped by
  default, not leaked.

On top of the allowlist, every string that IS kept (tool args, the agent's text,
diffs, paths, verify messages) is scrubbed: URLs, emails, IPs, bearer/api tokens,
long hex/secret-looking blobs are masked; home directories and temp/workdir roots
are collapsed so usernames and machine paths don't leak (the repo-relative tail is
preserved for analysis).

By DEFAULT raw tool OUTPUTS (stdout/results) are excluded — they are the largest
and least controllable leak surface and aren't needed for navigation analysis
(the tool ARGS already say what the agent searched for). Opt in with
--include-outputs (scrubbed AND truncated).

ALWAYS review the emitted file before sharing it. The script prints a redaction
report so you can sanity-check what it masked.

Usage:
    python3 tools/export_safe_trace.py <path> [-o out.json] \\
        [--include-outputs] [--max-output-chars 500] [--strip-prefix /repo/root]

<path> may be a trace.json, a run dir (containing trace.json), or a runs root
(any dir with <cond>/rep_N/trace.json beneath it) — all matching traces are
bundled into one reviewable file.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

SCHEMA = "abench-safe-trace/v1"

# ── Scrubbers (ordered; URLs before paths since URLs contain '//') ───────────
# Each entry: (category, compiled regex, replacement).
_SCRUBBERS: list[tuple[str, re.Pattern, str]] = [
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "<email>"),
    ("url", re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s'\"<>)\]]+", re.I), "<url>"),
    # secret-ish provider tokens (OpenAI/GitHub/Slack/Bearer/api-key=...)
    ("secret", re.compile(
        r"\b(?:sk-[A-Za-z0-9]{6,}|gh[pousr]_[A-Za-z0-9]{6,}|xox[baprs]-[A-Za-z0-9-]{6,})\b"),
        "<secret>"),
    ("secret", re.compile(
        r"(?i)\b(?:bearer|authorization|api[_-]?key|token|secret|password|passwd)\b"
        r"\s*[:=]?\s*[^\s'\"]+"),
        "<secret>"),
    ("ip", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b"), "<ip>"),
    ("hex", re.compile(r"\b[0-9a-fA-F]{24,}\b"), "<hex>"),
    # temp / workdir roots → collapse machine-specific gibberish, keep the tail
    ("tmp", re.compile(r"(?:/private)?/var/folders/[A-Za-z0-9_+/-]+?/T/?"), "<tmp>/"),
    ("workdir", re.compile(r"\babench-[A-Za-z0-9._-]+"), "abench-<id>"),
    # home directories → drop the username, keep "~"
    ("home", re.compile(r"/(?:Users|home)/[^/\s'\"]+"), "~"),
    ("home", re.compile(r"[A-Za-z]:\\Users\\[^\\\s'\"]+"), r"~"),
]


class Scrubber:
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
        """Recursively scrub strings inside dicts/lists; keep keys and non-strings."""
        if isinstance(o, str):
            return self.text(o)
        if isinstance(o, dict):
            return {k: self.obj(v) for k, v in o.items()}
        if isinstance(o, list):
            return [self.obj(v) for v in o]
        return o  # int/float/bool/None pass through


# ── Allowlisted projections ──────────────────────────────────────────────────
def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def safe_step(step: dict, base_ts, scr: Scrubber, *, include_outputs: bool,
              max_output_chars: int) -> dict:
    """Project ONE step down to allowlisted, scrubbed fields."""
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
        out["args"] = scr.obj(step["tool_args"])
    if step.get("path"):
        out["path"] = scr.text(step["path"])
    if step.get("patch"):
        out["patch"] = scr.text(step["patch"])
    if step.get("text"):
        out["text"] = scr.text(step["text"])
    ec = step.get("exit_code")
    if ec is not None:
        out["exit_code"] = ec
    if include_outputs and step.get("output"):
        raw = str(step["output"])
        clipped = raw[:max_output_chars]
        out["output"] = scr.text(clipped) + ("…[truncated]" if len(raw) > max_output_chars else "")
    return out


def safe_trace(trace: dict, manifest: dict, scr: Scrubber, *,
               include_outputs: bool, max_output_chars: int) -> dict:
    steps_in = trace.get("steps") or []
    base_ts = _num(trace.get("started_at"))
    steps = [safe_step(s, base_ts, scr, include_outputs=include_outputs,
                        max_output_chars=max_output_chars)
             for s in steps_in if isinstance(s, dict)]

    by_name: Counter = Counter()
    for s in steps:
        if s.get("kind") == "tool_call" and s.get("tool"):
            by_name[s["tool"]] += 1

    started, ended = base_ts, _num(trace.get("ended_at"))
    duration = round(ended - started, 1) if started is not None and ended is not None else None

    out = {
        "condition": manifest.get("condition"),
        "rep": manifest.get("rep"),
        "duration_s": duration,
        "n_steps": len([s for s in steps if s.get("kind") in (None, "tool_call",
                        "assistant_text", "reasoning", "file_edit")]) or len(steps),
        "n_tool_calls": sum(by_name.values()),
        "tool_calls_by_name": dict(by_name),
        "finished": trace.get("finished"),
        "interrupted_reason": scr.text(trace.get("interrupted_reason")),
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
    return out


# ── Discovery / IO ────────────────────────────────────────────────────────────
def _find_traces(path: Path) -> list[Path]:
    if path.is_file() and path.name == "trace.json":
        return [path]
    if path.is_dir():
        direct = path / "trace.json"
        if direct.is_file():
            return [direct]
        return sorted(path.rglob("trace.json"))
    return []


def _load_manifest(trace_path: Path) -> dict:
    mf = trace_path.parent / "manifest.json"
    if mf.is_file():
        try:
            m = json.loads(mf.read_text())
            return {"condition": m.get("condition"), "rep": m.get("rep")}
        except (OSError, ValueError):
            pass
    # Fall back to the on-disk layout: <condition>/rep_N/
    parent = trace_path.parent
    rep = None
    if parent.name.startswith("rep_"):
        try:
            rep = int(parent.name.removeprefix("rep_"))
        except ValueError:
            rep = None
    cond = parent.parent.name if parent.name.startswith("rep_") else None
    return {"condition": cond, "rep": rep}


def build_bundle(path: Path, *, include_outputs: bool, max_output_chars: int,
                 strip_prefix: str | None) -> tuple[dict, Counter]:
    scr = Scrubber(strip_prefix)
    traces = []
    for tp in _find_traces(path):
        try:
            data = json.loads(tp.read_text())
        except (OSError, ValueError):
            continue
        traces.append(safe_trace(data, _load_manifest(tp), scr,
                                  include_outputs=include_outputs,
                                  max_output_chars=max_output_chars))
    bundle = {
        "schema": SCHEMA,
        "policy": "allowlist; outputs " + ("included(scrubbed+truncated)" if include_outputs
                                           else "excluded"),
        "n_traces": len(traces),
        "redaction": dict(scr.counts),
        "traces": traces,
    }
    return bundle, scr.counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Export a redacted, share-safe trace view.")
    ap.add_argument("path", help="trace.json, a run dir, or a runs root")
    ap.add_argument("-o", "--output", help="output file (default: <path>/safe-traces.json)")
    ap.add_argument("--include-outputs", action="store_true",
                    help="include tool outputs (scrubbed AND truncated). Off by default.")
    ap.add_argument("--max-output-chars", type=int, default=500)
    ap.add_argument("--strip-prefix", default=None,
                    help="absolute repo/workdir root to make paths repo-relative")
    args = ap.parse_args(argv)

    path = Path(args.path)
    if not path.exists():
        ap.error(f"path not found: {path}")
    bundle, counts = build_bundle(
        path, include_outputs=args.include_outputs,
        max_output_chars=args.max_output_chars, strip_prefix=args.strip_prefix)

    if bundle["n_traces"] == 0:
        ap.error(f"no trace.json found under {path}")

    out = Path(args.output) if args.output else (
        path.parent / "safe-traces.json" if path.is_file() else path / "safe-traces.json")
    out.write_text(json.dumps(bundle, indent=2, ensure_ascii=False))

    print(f"wrote {bundle['n_traces']} trace(s) → {out}")
    print(f"outputs: {'INCLUDED (scrubbed+truncated)' if args.include_outputs else 'excluded'}")
    if counts:
        print("redactions: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    else:
        print("redactions: none matched")
    print("→ REVIEW this file before sharing it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
