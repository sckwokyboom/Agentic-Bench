#!/usr/bin/env python3
"""Export a REDACTED, share-safe view of an agent run's trace (standalone, stdlib-only).

Built to run on a locked-down / corporate machine and emit a file you can review
and hand off for trace analysis. It carries only what's needed to study the agent
loop — tool calls, their arguments, the diffs the agent produced, and the agent's
own text/reasoning — and nothing else.

The redaction policy (allowlist + scrubbing) lives in ``abench/safe_trace.py`` so
the CLI and the Web UI share one source of truth. See that module's docstring.

By DEFAULT raw tool OUTPUTS are excluded — opt in with --include-outputs
(scrubbed AND truncated). ALWAYS review the emitted file before sharing it.

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
import sys
from pathlib import Path

# Run as a loose script (sys.path[0] is tools/, not the repo root) → make the
# abench package importable so the shared redaction core can be reused.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from abench.safe_trace import build_bundle  # noqa: E402


def find_traces(path: Path) -> list[Path]:
    if path.is_file() and path.name == "trace.json":
        return [path]
    if path.is_dir():
        direct = path / "trace.json"
        if direct.is_file():
            return [direct]
        return sorted(path.rglob("trace.json"))
    return []


def load_manifest(trace_path: Path) -> dict:
    mf = trace_path.parent / "manifest.json"
    if mf.is_file():
        try:
            m = json.loads(mf.read_text())
            return {"condition": m.get("condition"), "rep": m.get("rep")}
        except (OSError, ValueError):
            pass
    parent = trace_path.parent  # fall back to the <condition>/rep_N/ layout
    if parent.name.startswith("rep_"):
        try:
            return {"condition": parent.parent.name,
                    "rep": int(parent.name.removeprefix("rep_"))}
        except ValueError:
            pass
    return {"condition": None, "rep": None}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Export a redacted, share-safe trace view.")
    ap.add_argument("path", help="trace.json, a run dir, or a runs root")
    ap.add_argument("-o", "--output", help="output file (default: <path>/safe-traces.json)")
    ap.add_argument("--include-outputs", action="store_true",
                    help="include tool outputs (scrubbed AND truncated). Off by default.")
    ap.add_argument("--digest", action="store_true",
                    help="compact navigation skeleton: diff bodies → +/- counts, "
                         "agent text truncated, long args clipped. Much smaller; "
                         "ideal for pasting into a chat.")
    ap.add_argument("--max-output-chars", type=int, default=500)
    ap.add_argument("--strip-prefix", default=None,
                    help="absolute repo/workdir root to make paths repo-relative")
    args = ap.parse_args(argv)

    path = Path(args.path)
    if not path.exists():
        ap.error(f"path not found: {path}")

    items = []
    for tp in find_traces(path):
        try:
            items.append((json.loads(tp.read_text()), load_manifest(tp)))
        except (OSError, ValueError):
            continue
    if not items:
        ap.error(f"no trace.json found under {path}")

    bundle = build_bundle(items, include_outputs=args.include_outputs,
                          max_output_chars=args.max_output_chars,
                          strip_prefix=args.strip_prefix, digest=args.digest)

    out = Path(args.output) if args.output else (
        path.parent / "safe-traces.json" if path.is_file() else path / "safe-traces.json")
    out.write_text(json.dumps(bundle, indent=2, ensure_ascii=False))

    print(f"wrote {bundle['n_traces']} trace(s) → {out}")
    print(f"outputs: {'INCLUDED (scrubbed+truncated)' if args.include_outputs else 'excluded'}")
    counts = bundle["redaction"]
    print("redactions: " + (", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
                            if counts else "none matched"))
    print("→ REVIEW this file before sharing it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
