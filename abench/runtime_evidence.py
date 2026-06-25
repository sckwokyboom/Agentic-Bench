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
