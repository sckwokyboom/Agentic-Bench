#!/usr/bin/env python3
"""Rank Defects4J bugs as RCC-demo / agent-hard candidates from METADATA ONLY
(no builds, no network). Point it at a Defects4J checkout's framework/projects.

Usage:
    python3 defects4j_select.py [/path/to/defects4j/framework/projects] \
        [--trig N] [--maxcls M] [--focus Closure,Math,...]

Per-bug signals read from framework/projects/<P>/:
    triggers     = # lines starting '---' in trigger_tests/<id>   (cascade width)
    mod_classes  = # lines in modified_classes/<id>.src           (fix localization)
    files, hunks = parsed from patches/<id>.src.patch             (patch spread)
    nonlocal     = trigger-test package(s) disjoint from modified-class package(s)
                   (the failure surfaces FAR from the fix — symptom != cause)

Two shortlists:
    RCC-ideal  : focus project + triggers>=TRIG + mod_classes<=MAXCLS + nonlocal
                 (single known target + wide non-local cascade — RCC's niche)
    agent-hard : focus project + (mod_classes>=2 or files>=2 or hunks>=3)
                 (multi-site fix — a plain agent tends to fix one spot, miss others)

NOTE: these are STATIC proxies. "The baseline agent actually fails" must still be
MEASURED by running opencode+deepseek (no augmentation) on the candidates — that is
the only reliable filter. This script produces the candidate pool to run.
Metadata layout is stable across recent Defects4J but sanity-check the paths against
your checkout (active-bugs.csv / trigger_tests/ / modified_classes/ / patches/).
"""
from __future__ import annotations

import argparse
import re
import statistics
from collections import defaultdict
from pathlib import Path

DEFAULT_FOCUS = ["Closure", "Math", "JacksonDatabind", "Jsoup", "Lang", "Compress"]


def _pkg(fqn: str) -> str:
    return fqn.rsplit(".", 1)[0] if "." in fqn else ""


def _bug_ids(base: Path) -> list[str]:
    csv = base / "active-bugs.csv"
    if csv.exists():
        return [ln.split(",", 1)[0].strip()
                for ln in csv.read_text().splitlines()[1:] if ln.strip()]
    # older layout fallback: commit-db
    cdb = base / "commit-db"
    if cdb.exists():
        return [ln.split(",", 1)[0].strip()
                for ln in cdb.read_text().splitlines() if ln.strip()]
    return []


def analyze(projdir: Path) -> list[dict]:
    rows: list[dict] = []
    for P in sorted(p.name for p in projdir.iterdir() if p.is_dir()):
        base = projdir / P
        for bid in _bug_ids(base):
            tt = base / "trigger_tests" / bid
            if not tt.exists():
                continue
            trig_lines = [l for l in tt.read_text(errors="replace").splitlines()
                          if l.startswith("---")]
            trig_classes = set()
            for l in trig_lines:
                m = re.match(r"---\s+([\w.$]+)(?:::|\.)[\w$]+", l)
                if m:
                    trig_classes.add(m.group(1))
            mc = base / "modified_classes" / f"{bid}.src"
            modc = ([l.strip() for l in mc.read_text().splitlines() if l.strip()]
                    if mc.exists() else [])
            pt = base / "patches" / f"{bid}.src.patch"
            files = hunks = 0
            if pt.exists():
                t = pt.read_text(errors="replace")
                files = t.count("\n+++ ") or t.count("+++ ")
                hunks = t.count("@@ ")
            nonlocal_ = bool(trig_classes) and bool(modc) and not (
                {_pkg(c) for c in trig_classes} & {_pkg(m) for m in modc})
            rows.append(dict(project=P, bug=bid, triggers=len(trig_lines),
                             mod_classes=len(modc), files=files, hunks=hunks,
                             nonlocal_=nonlocal_))
    return rows


def summary(rows: list[dict]) -> None:
    by = defaultdict(list)
    for r in rows:
        by[r["project"]].append(r)
    print(f"\n=== dataset summary ({len(rows)} bugs, {len(by)} projects) ===")
    print(f"{'project':16}{'bugs':>5}{'medTrig':>8}{'trig>=5':>8}"
          f"{'trig>=10':>9}{'1cls+casc+nonloc':>18}")
    for P in sorted(by, key=lambda k: -len(by[k])):
        rs = by[P]
        med = statistics.median(r["triggers"] for r in rs) if rs else 0
        t5 = sum(r["triggers"] >= 5 for r in rs)
        t10 = sum(r["triggers"] >= 10 for r in rs)
        sweet = sum(r["triggers"] >= 5 and r["mod_classes"] <= 1 and r["nonlocal_"]
                    for r in rs)
        print(f"{P:16}{len(rs):>5}{med:>8.0f}{t5:>8}{t10:>9}{sweet:>18}")


def _show(title: str, rs: list[dict], limit: int = 40) -> None:
    print(f"\n== {title} ({len(rs)}) ==")
    print(f"{'project':16}{'bug':>5}{'trig':>6}{'mcls':>6}{'files':>6}"
          f"{'hunks':>6}  nonlocal")
    for r in rs[:limit]:
        print(f"{r['project']:16}{r['bug']:>5}{r['triggers']:>6}{r['mod_classes']:>6}"
              f"{r['files']:>6}{r['hunks']:>6}  {r['nonlocal_']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("projects", nargs="?", default="framework/projects")
    ap.add_argument("--trig", type=int, default=4, help="min triggering tests (cascade)")
    ap.add_argument("--maxcls", type=int, default=1, help="max modified classes (target)")
    ap.add_argument("--focus", default=",".join(DEFAULT_FOCUS))
    a = ap.parse_args()
    focus = {s.strip() for s in a.focus.split(",") if s.strip()}

    rows = analyze(Path(a.projects))
    if not rows:
        print("No bugs found — is the path a Defects4J framework/projects dir?")
        return
    summary(rows)

    ideal = [r for r in rows if r["project"] in focus and r["triggers"] >= a.trig
             and r["mod_classes"] <= a.maxcls and r["nonlocal_"]]
    hard = [r for r in rows if r["project"] in focus and
            (r["mod_classes"] >= 2 or r["files"] >= 2 or r["hunks"] >= 3)]
    ideal.sort(key=lambda r: (-r["triggers"], r["hunks"]))
    hard.sort(key=lambda r: (-(r["hunks"] + r["files"]), -r["triggers"]))
    _show(f"RCC-ideal: {focus} + trig>={a.trig} + mod_classes<={a.maxcls} + non-local",
          ideal)
    _show(f"agent-hard: {focus} + multi-site (>=2 classes / >=2 files / >=3 hunks)", hard)
    print(f"\npick >=10 from RCC-ideal (loosen --maxcls 2 / --trig 3 if thin); "
          f"then MEASURE baseline failure on them before the rcc A/B.")


if __name__ == "__main__":
    main()
