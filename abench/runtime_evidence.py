"""Host-side: turn the runtime probe's capture (.runtime-capture.jsonl) into a
tight, ranked diagnostic card for the phased DIAGNOSE prompt (phased-runtime
ablation). Pure + tolerant: a malformed/empty/absent capture yields no card."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# Frames to drop from a corridor — test framework / JVM internals / the probe.
_DROP = ("org.junit", "org.gradle", "worker.org", "jdk.", "java.", "sun.",
         "javax.", "net.bytebuddy", "abench.probe")


@dataclass
class CaptureEvent:
    method: str
    args: list[str] = field(default_factory=list)
    stack: list[str] = field(default_factory=list)
    thrown: str | None = None
    exit: bool = False


def parse_capture(path) -> list[CaptureEvent]:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out: list[CaptureEvent] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict) or "method" not in d:
            continue
        out.append(CaptureEvent(
            method=str(d.get("method", "")),
            args=[str(a) for a in (d.get("args") or [])],
            stack=[str(s) for s in (d.get("stack") or [])],
            thrown=d.get("throw"),
            exit=bool(d.get("exit")),
        ))
    return out


def trim_corridor(stack: list[str], keep: int = 6) -> list[str]:
    """Keep the top app frames (closest to the method), dropping framework/JVM."""
    return [f for f in stack if not f.startswith(_DROP)][:keep]


def build_card(events: list[CaptureEvent], target_label: str, *,
               max_examples: int = 3, corridor_keep: int = 6) -> str | None:
    """A tight, provenance-marked diagnostic card from this run's capture.
    Evidence only — never prescribes a fix (else the ablation would measure our
    heuristic, not the value of the evidence)."""
    enters = [e for e in events if not e.exit]
    exits = [e for e in events if e.exit]
    if not enters and not exits:
        return None

    seen: set = set()
    uniq: list[tuple[tuple, list[str]]] = []
    for e in enters:
        corr = tuple(trim_corridor(e.stack, corridor_keep))
        key = (corr, tuple(e.args))
        if key in seen:
            continue
        seen.add(key)
        uniq.append((corr, e.args))

    throws = sorted({e.thrown for e in exits if e.thrown})

    lines = [
        f"RUNTIME EVIDENCE for {target_label} "
        f"(captured THIS run; src: method-entry probe — actual values + call path):",
        f"  observed {len(enters)} call(s); {len(uniq)} distinct path/arg shape(s)",
    ]
    for i, (corr, args) in enumerate(uniq[:max_examples], 1):
        shown = ", ".join(a if a != "" else "(empty)" for a in args) if args else "(no args)"
        lines.append(f"  [{i}] args: {shown}")
        if corr:
            lines.append("      corridor: " + " <- ".join(corr))
    for t in throws[:2]:
        lines.append(f"  throws: {t}")
    lines.append("  (evidence only — find the COMMON root cause; do not curve-fit a single call)")
    return "\n".join(lines)
