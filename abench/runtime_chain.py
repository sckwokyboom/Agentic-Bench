"""Host-side: turn the CHAIN-mode probe capture (the Recorder's JSONL — a per-call
corridor dump with per-frame runtime args + per-activation exit ret/throw) into an
enriched diagnostic card: the call path (outer caller → target) with the runtime
values each hop received and what it returned/threw. Pure + tolerant.

Separate from runtime_evidence.py, which parses the single-target (ProbeAdvice)
format {method,args,stack}+{throw}; this parses {target,corridor:[…]}+{act,exit}."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ChainCall:
    target: str
    frames: list[dict] = field(default_factory=list)   # [{act, method, args:[str]}], target-first


def parse_chain(path) -> "tuple[list[ChainCall], dict]":
    """Parse the chain capture → (corridors, exits). corridors: one ChainCall per
    dump line (frames target-first, as the shadow stack iterates). exits: keyed by
    activation id → {"ret": str} or {"throw": str}."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], {}
    corridors: list[ChainCall] = []
    exits: dict = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        if d.get("exit"):
            act = d.get("act")
            if act is not None:
                exits[act] = ({"throw": str(d["throw"])} if d.get("throw") is not None
                              else {"ret": str(d.get("ret", ""))})
        elif "corridor" in d:
            frames = [{"act": fr.get("act"), "method": str(fr.get("method", "")),
                       "args": [str(a) for a in (fr.get("args") or [])]}
                      for fr in (d.get("corridor") or []) if isinstance(fr, dict)]
            corridors.append(ChainCall(target=str(d.get("target", "")), frames=frames))
    return corridors, exits


def _short(method: str) -> str:
    """picocli.CommandLine$Help$TextTable.putValue -> TextTable.putValue."""
    cls, _, m = method.rpartition(".")
    simple = cls.split(".")[-1].split("$")[-1] if cls else ""
    return f"{simple}.{m}" if simple else m


def build_chain_card(corridors: "list[ChainCall]", exits: dict, target_label: str,
                     *, max_examples: int = 2) -> "str | None":
    """Enriched card: the call path (outer → target) with per-frame runtime args and
    each frame's return/throw. Evidence only — never prescribes a fix (else the
    ablation would measure our heuristic, not the value of the evidence)."""
    if not corridors:
        return None

    seen: set = set()
    uniq: list[ChainCall] = []
    for c in corridors:
        key = (tuple(f["method"] for f in c.frames),
               tuple(tuple(f["args"]) for f in c.frames))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)

    lines = [f"RUNTIME CHAIN for {target_label} "
             "(captured THIS run; per-frame runtime args along the call path):"]
    for ci, c in enumerate(uniq[:max_examples], 1):
        if len(uniq) > 1:
            lines.append(f"  [path {ci} of {len(uniq)}]")
        # frames are target-first; render reversed (outer caller → target) so it
        # reads as the call descending into the target.
        ordered = list(reversed(c.frames))
        for i, f in enumerate(ordered):
            args = ", ".join(a if a != "" else "(empty)" for a in f["args"]) if f["args"] else ""
            ex = exits.get(f["act"], {})
            if "throw" in ex:
                tail = f"  → throws {ex['throw']}"
            elif ex.get("ret") and ex["ret"] != "void":
                tail = f"  → {ex['ret']}"
            else:
                tail = ""
            arrow = "" if i == 0 else "→ "
            lines.append(f"    {arrow}{_short(f['method'])}({args}){tail}")
    lines.append("  (evidence only — what the code actually received + did; "
                 "find the COMMON root cause, do not curve-fit a single call)")
    return "\n".join(lines)
