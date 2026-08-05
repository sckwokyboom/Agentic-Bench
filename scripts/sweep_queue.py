#!/usr/bin/env python3
"""Queue a whole sweep through the RUNNING abench-ui, one experiment at a time.

The UI starts one experiment per click and has no batch concept, but its own API is
enough to build one: POST /api/runs creates exactly the session a click would, and
GET /api/sessions lists in-flight sessions so the UI "can always offer a way back to a
live run after the tab was closed". So a queued run is not a side channel — it shows up
in the UI as an ordinary session, with the live ReAct stream, traces and metrics, and
it can be watched or abandoned freely.

That is the difference from run_sweep.sh: the shell batch is fine unattended, but its
runs are only visible after the fact. This one is watchable while it happens.

Experiments run STRICTLY one at a time. Two agent sessions sharing a machine would
contend for CPU during their gradle verifies, and duration is one of the numbers being
measured.

    abench-ui --experiments-dir picocli-sweep &          # the UI you already use
    python3 scripts/sweep_queue.py --experiments-dir picocli-sweep --reps 3
    python3 scripts/sweep_queue.py --only putValue,Interpreter-consumeMapArguments
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DONE = ("done", "finished", "completed", "failed", "error", "cancelled", "canceled")


def _api(base: str, path: str, payload: dict | None = None, method: str | None = None):
    url = f"{base.rstrip('/')}/api{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method or ("POST" if data else "GET"),
        headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read().decode("utf-8", "replace")
    return json.loads(body) if body.strip() else None


def wait_for(base: str, sid: str, poll: float, quiet_after: float) -> dict:
    """Block until the session leaves pending/running, reporting progress."""
    last, silent_since = None, time.monotonic()
    while True:
        try:
            s = _api(base, f"/sessions/{sid}")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                # Sessions are in-memory: a finished one can fall out of the active
                # list, and that is a completion, not an error.
                return {"state": "gone", "session_id": sid}
            raise
        state = str(s.get("state", "")).lower()
        now = (s.get("current_idx"), s.get("current_condition"), s.get("current_rep"))
        if now != last:
            idx, cond, rep = now
            print(f"      run {(idx or 0) + 1}/{s.get('total_runs') or '?'} "
                  f"[{cond or '…'} rep {rep if rep is not None else '…'}]", flush=True)
            last, silent_since = now, time.monotonic()
        elif time.monotonic() - silent_since > quiet_after:
            print(f"      … still on the same run after "
                  f"{int((time.monotonic() - silent_since) / 60)} min", flush=True)
            silent_since = time.monotonic()
        if state in DONE:
            return s
        time.sleep(poll)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8765",
                    help="where abench-ui is serving")
    ap.add_argument("--experiments-dir", type=Path,
                    help="only used to order/validate names locally (optional)")
    ap.add_argument("--only", help="comma-separated experiment names (default: all)")
    ap.add_argument("--conditions", help="comma-separated subset, e.g. baseline,rcc")
    ap.add_argument("--reps", type=int, help="override repetitions per condition")
    ap.add_argument("--poll", type=float, default=10.0)
    ap.add_argument("--quiet-after", type=float, default=900.0,
                    help="seconds of no progress before saying so")
    a = ap.parse_args()

    try:
        listing = _api(a.base, "/experiments")
    except urllib.error.URLError as exc:
        print(f"cannot reach abench-ui at {a.base}: {exc}\n"
              f"  start it first:  abench-ui --experiments-dir "
              f"{a.experiments_dir or '<dir>'}")
        return 2
    names = [e["name"] for e in listing]
    if a.only:
        want = [n.strip() for n in a.only.split(",")]
        missing = [n for n in want if n not in names]
        if missing:
            print(f"not served by this UI: {missing}\n  it lists: {names}")
            return 2
        names = want
    if not names:
        print("the UI lists no experiments — check --experiments-dir on the server")
        return 2

    conditions = [c.strip() for c in a.conditions.split(",")] if a.conditions else None
    print(f"queueing {len(names)} experiment(s) through {a.base}, one at a time:")
    for n in names:
        print(f"  - {n}")
    print("watch them live in the UI; this process only sequences them.\n")

    results, t_all = [], time.monotonic()
    for i, name in enumerate(names, 1):
        print(f"[{i}/{len(names)}] {name}", flush=True)
        body = {"experiment_name": name}
        if conditions:
            body["conditions"] = conditions
        if a.reps:
            body["repetitions"] = a.reps
        t0 = time.monotonic()
        try:
            started = _api(a.base, "/runs", body)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:200]
            print(f"      could not start: HTTP {exc.code} {detail}")
            results.append((name, "not started", 0))
            continue
        sid = started.get("session_id") or started.get("sid")
        if not sid:
            print(f"      unexpected response: {started}")
            results.append((name, "no session id", 0))
            continue
        final = wait_for(a.base, sid, a.poll, a.quiet_after)
        mins = (time.monotonic() - t0) / 60
        print(f"      {final.get('state')} after {mins:.0f} min\n", flush=True)
        results.append((name, str(final.get("state")), round(mins)))

    print(f"queue finished in {(time.monotonic() - t_all) / 60:.0f} min")
    for name, state, mins in results:
        print(f"  {name:38} {state:12} {mins:>4} min")
    print("\nAggregate the comparison with:\n"
          f"  python3 scripts/d4j_ab_summary.py {a.experiments_dir or '<root>'} "
          f"--runs-dir runs --out picocli-ab.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
