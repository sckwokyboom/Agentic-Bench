#!/usr/bin/env python3
"""Collect what FAILED in a batch into one paste-able file.

Every run writes run.log / debug.log / events.jsonl / error.log under its own rep dir,
so diagnosing a batch means opening dozens of files — and the console scrollback is
usually gone by then. This gathers the failures only: crash tracebacks, and the tail
of any run whose log carries a known failure signature.

    python3 scripts/swe_logs.py                       # every swe-runs*/swe-probe-* root
    python3 scripts/swe_logs.py --roots swe-probe-dubbo --out logs.md
"""
from __future__ import annotations

import argparse
import glob
import re
from pathlib import Path

TAIL = 25          # lines of run.log kept per failing run
MAX_RUNS = 40      # keep the report paste-able

#: Failure signatures worth pulling out by name. The first three are environment
#: faults that masquerade as agent failures, which is exactly what makes them
#: expensive to diagnose late.
SIGNATURES = {
    "I/O error (filesystem)": re.compile(
        r"Input/output error|Structure needs cleaning|No space left|Stale file handle", re.I),
    "git failure": re.compile(r"fatal: .*\.git|could not lock|index\.lock|"
                              r"unable to (read|write) .*\.git", re.I),
    "proxy/auth": re.compile(r"Proxy Authentication Required|407|"
                             r"401 Unauthorized|403 Forbidden", re.I),
    "rate limit / provider": re.compile(r"429|rate.?limit|service unavailable|502|503", re.I),
    "build failure": re.compile(r"BUILD FAILURE|COMPILATION ERROR|Could not resolve|"
                                r"Non-resolvable parent POM", re.I),
    "timeout": re.compile(r"timed out|TimeoutExpired", re.I),
}


def _read(p: Path, limit: int = 200_000) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError as exc:
        return f"<<could not read {p}: {exc}>>"


def scan_run(rundir: Path) -> dict | None:
    """A failing run's evidence, or None when nothing looks wrong."""
    hits: list[str] = []
    text = ""
    for name in ("run.log", "debug.log"):
        f = rundir / name
        if f.is_file():
            text += _read(f)
    for label, rx in SIGNATURES.items():
        if rx.search(text):
            hits.append(label)
    err = rundir / "error.log"
    if not hits and not err.is_file():
        return None
    return {"rundir": rundir, "hits": hits,
            "error": _read(err, 4000) if err.is_file() else None,
            "tail": "\n".join(text.strip().splitlines()[-TAIL:])}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--roots", nargs="*",
                    help="run roots (default: swe-runs*, swe-probe-*, d4j-runs)")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    roots = a.roots or sorted(glob.glob("swe-runs*") + glob.glob("swe-probe-*")
                              + glob.glob("d4j-runs"))
    roots = [Path(r) for r in roots if Path(r).is_dir()]
    if not roots:
        print("no run roots found here")
        return 1

    rundirs: list[Path] = []
    for root in roots:
        rundirs += [p for p in root.glob("*/runs*/*/*/*/rep_*") if p.is_dir()]
    found = [r for r in (scan_run(d) for d in sorted(rundirs)) if r]

    o = ["# Batch failures", "",
         f"roots: {', '.join(str(r) for r in roots)} | runs scanned: {len(rundirs)} | "
         f"with problems: **{len(found)}**", ""]
    if not found:
        o += ["Nothing matched a known failure signature and no run crashed.", ""]
    else:
        tally: dict[str, int] = {}
        for r in found:
            for h in r["hits"]:
                tally[h] = tally.get(h, 0) + 1
        if tally:
            o += ["| signature | runs |", "|---|---|"]
            o += [f"| {k} | {v} |" for k, v in sorted(tally.items(), key=lambda x: -x[1])]
            o.append("")
        for r in found[:MAX_RUNS]:
            o += [f"### `{r['rundir']}`",
                  f"signatures: {', '.join(r['hits']) or '(crashed)'}", ""]
            if r["error"]:
                o += ["```", r["error"].strip()[-1500:], "```"]
            if r["tail"]:
                o += ["<details><summary>log tail</summary>", "", "```",
                      r["tail"][-2500:], "```", "</details>", ""]
        if len(found) > MAX_RUNS:
            o.append(f"_…and {len(found) - MAX_RUNS} more (capped for readability)_")
    text = "\n".join(o)
    print(text)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
        print(f"\n[written to {a.out}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
