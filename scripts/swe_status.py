#!/usr/bin/env python3
"""Progress of a fixture-mode A/B batch, read off disk — safe to run WHILE it runs.

A batch is hours long and its only live signal is a log tail. This reads the run tree
instead: what is finished, what is in flight, what has not started, and how long the
current session has been going — from another terminal, without touching the batch.

    python3 scripts/swe_status.py                  # ./swe-runs
    python3 scripts/swe_status.py d4j-runs --runs-dir runs-ab
    watch -n 30 python3 scripts/swe_status.py      # live
"""
from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

_REPS = re.compile(r"^repetitions:\s*(\d+)", re.M)
_COND = re.compile(r"^\s*-\s*\{?\s*name:\s*([\w.-]+)", re.M)


def _expected(fixture: Path) -> tuple[int, list[str]]:
    """(reps, arm names) from the experiment yaml — no yaml dependency needed."""
    y = fixture / "experiment.yaml"
    if not y.is_file():
        return 0, []
    text = y.read_text(encoding="utf-8", errors="replace")
    m = _REPS.search(text)
    # Condition names live under `conditions:`; take the tail of the file after it.
    tail = text.split("conditions:", 1)[-1]
    return (int(m.group(1)) if m else 1), _COND.findall(tail)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default="swe-runs", type=Path)
    ap.add_argument("--runs-dir", default="runs",
                    help="'runs' for the SWE fixtures, 'runs-ab' for the Defects4J A/B")
    a = ap.parse_args()
    if not a.root.is_dir():
        print(f"no such run root: {a.root}")
        return 2

    fixtures = sorted(p for p in a.root.iterdir()
                      if p.is_dir() and (p / "experiment.yaml").is_file())
    if not fixtures:
        print(f"no fixtures under {a.root} — run: ./scripts/swe.sh build")
        return 1

    now = time.time()
    done_all = todo_all = 0
    rows, active = [], []
    for f in fixtures:
        reps, arms = _expected(f)
        want = reps * max(len(arms), 1)
        reps_done = list(f.glob(f"{a.runs_dir}/*/*/*/rep_*/metrics.json"))
        # A rep dir without metrics.json is either running now or died mid-way.
        started = [p for p in f.glob(f"{a.runs_dir}/*/*/*/rep_*") if p.is_dir()]
        in_flight = [p for p in started if not (p / "metrics.json").is_file()]
        done_all += len(reps_done)
        todo_all += want
        for p in in_flight:
            active.append((f.name, f"{p.parent.name}/{p.name}", now - p.stat().st_mtime))
        state = ("done" if len(reps_done) >= want else
                 "running" if in_flight else
                 "partial" if reps_done else "pending")
        rows.append((f.name, len(reps_done), want, state))

    width = max(len(r[0]) for r in rows)
    print(f"{'fixture':<{width}}  done  state")
    for name, d, w, state in rows:
        print(f"{name:<{width}}  {d}/{w}   {state}")
    pct = (100 * done_all / todo_all) if todo_all else 0
    print(f"\noverall: {done_all}/{todo_all} sessions ({pct:.0f}%)")
    if active:
        print("\nin flight:")
        for name, arm, age in active:
            mins = age / 60
            note = "  <-- no file activity for a while; check the log" if mins > 45 else ""
            print(f"  {name} [{arm}] — {mins:.0f} min{note}")
    elif done_all < todo_all:
        print("nothing in flight — the batch is not running (resume: ./scripts/swe.sh run)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
