"""Local augmentation checker — render the runtime diagnostic cards from a probe
capture so the augmentations can be verified WITHOUT the sandbox: against a
committed fixture, or against a real capture copied from a run (host or WSL).

Auto-detects the capture format:
  - chain   : Recorder JSONL ({target,corridor:[…]} + {act,exit})  -> runtime_chain
  - single  : ProbeAdvice JSONL ({method,args,stack} + {throw})    -> runtime_evidence

Usage:
  python3 -m abench.augcheck <capture.jsonl> [<capture2.jsonl> …] [--target LABEL]
"""
from __future__ import annotations

import sys
from pathlib import Path


def detect_format(path) -> str:
    """'chain' if any line is a corridor dump; 'single' if any carries a stack;
    'empty' otherwise (missing / unrecognized)."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "empty"
    chain = single = False
    for line in text.splitlines():
        if '"corridor"' in line:
            chain = True
        elif '"stack"' in line:
            single = True
    if chain:
        return "chain"
    if single:
        return "single"
    return "empty"


def render(path, target_label: str = "the target method") -> str:
    """Render the appropriate card for a capture (the exact text the controller would
    inject). Returns a human-readable note when nothing renders."""
    fmt = detect_format(path)
    if fmt == "chain":
        from .runtime_chain import build_chain_card, parse_chain
        corridors, exits = parse_chain(path)
        return build_chain_card(corridors, exits, target_label) or "(chain capture present but empty)"
    if fmt == "single":
        from .runtime_evidence import build_card, parse_capture
        return build_card(parse_capture(path), target_label) or "(single-target capture present but empty)"
    return "(no capture / unrecognized format)"


def main(argv: "list[str] | None" = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: python3 -m abench.augcheck <capture.jsonl> [...] [--target LABEL]",
              file=sys.stderr)
        return 2
    target = "the target method"
    paths: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == "--target" and i + 1 < len(argv):
            target = argv[i + 1]
            i += 2
        else:
            paths.append(argv[i])
            i += 1
    for p in paths:
        print(f"# {p}  [{detect_format(p)}]")
        print(render(p, target))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
