#!/usr/bin/env python3
"""Re-grade a Defects4J run by REPLAYING its source patch on a pristine checkout.

A run is graded in the agent's own workdir, which the agent can wreck: fabricating
a stub for a missing dependency, editing pom.xml, deleting a test to make the build
compile. Time-14 was graded FAILED with 20 failures in TestStringConvert — yet the
same +1/-1 patch on a clean tree passes everything; the failures came from a
joda-convert stub the agent had built, not from its code.

This isolates the code change from that damage: take the run's changes.patch, keep
ONLY the source hunks, apply them to a fresh copy of the pristine checkout, and run
`defects4j test` there. Disagreement with the recorded verdict means the recorded
one was about the environment, not the fix.

    python3 scripts/d4j_replay.py                  # replay the FAILED runs (candidates)
    python3 scripts/d4j_replay.py --all            # replay every graded run
    python3 scripts/d4j_replay.py Time-14 Lang-34  # replay specific bugs

Needs `defects4j` on PATH and abench importable. Each replay runs a full test
suite (minutes) — that is why the default is candidates only.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from d4j_sieve_summary import _bucket, _latest_run, _load  # noqa: E402

# The harness's own parser, so a replay verdict is comparable to the recorded one
# by construction rather than by a second, subtly different implementation.
from abench.verify import _parse_defects4j  # noqa: E402


def source_only_patch(patch_text: str) -> tuple[str, list[str], list[str]]:
    """Split a git patch into per-file blocks, keep the SOURCE ones.

    Returns (patch, kept_paths, dropped_paths). Dropping build output and tool
    noise is the point: replaying `all_tests` or a gradle cache would recreate the
    very pollution this check exists to remove.
    """
    blocks: list[tuple[str, list[str]]] = []
    cur: list[str] | None = None
    path = ""
    for line in patch_text.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if cur is not None:
                blocks.append((path, cur))
            cur, path = [line], line[len("diff --git "):].split(" b/")[-1].strip().strip('"')
        elif cur is not None:
            cur.append(line)
    if cur is not None:
        blocks.append((path, cur))

    kept, dropped, out = [], [], []
    for p, lines in blocks:
        if _bucket(p) == "src":
            kept.append(p)
            out.extend(lines)
        else:
            dropped.append(p)
    return "".join(out), kept, dropped


def _run(cmd: list[str], cwd: Path, timeout: int) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def all_runs(bugdir: Path, subdir: str) -> list[Path]:
    """Every graded rep under bugdir/<subdir> — the A/B writes one per condition
    per repetition, so replaying only the newest would silently grade one arm."""
    return sorted(p.parent for p in bugdir.glob(f"{subdir}/*/*/*/rep_*/metrics.json"))


def replay(bugdir: Path, timeout: int, rundir: Path | None = None) -> dict:
    """Apply the run's source patch to a pristine copy and re-grade it."""
    r: dict = {"bug": bugdir.name}
    if rundir is None:
        rundir = _latest_run(bugdir)
    if rundir is None:
        return {**r, "status": "no run"}
    # rep dir is <…>/<condition>/rep_N — label the row so arms stay distinguishable.
    r["arm"] = rundir.parent.name
    r["rep"] = rundir.name
    m = _load(rundir / "metrics.json") or {}
    r["recorded"] = m.get("verify_status")
    r["recorded_failed"] = m.get("verify_failed_count")

    patch_file = rundir / "changes.patch"
    if not patch_file.is_file():
        return {**r, "status": "no changes.patch"}
    patch, kept, dropped = source_only_patch(
        patch_file.read_text(encoding="utf-8", errors="replace"))
    r["kept"], r["dropped"] = kept, len(dropped)
    if not patch.strip():
        # No source change at all: the agent edited nothing gradeable.
        return {**r, "status": "empty source patch"}

    pristine = bugdir / "checkout"
    if not pristine.is_dir():
        return {**r, "status": "no pristine checkout"}

    tmp = Path(tempfile.mkdtemp(prefix=f"d4j-replay-{bugdir.name}-"))
    work = tmp / "t"
    try:
        shutil.copytree(pristine, work, symlinks=True)
        (tmp / "src.patch").write_text(patch, encoding="utf-8")
        rc, out = _run(["patch", "-p1", "--forward", "-i", str(tmp / "src.patch")],
                       work, timeout=120)
        if rc != 0:
            return {**r, "status": "patch failed", "detail": out.strip()[:300]}

        rc, out = _run(["defects4j", "test"], work, timeout=timeout)
        failing = (work / "failing_tests")
        alltests = (work / "all_tests")
        passed, failed, names = _parse_defects4j(
            failing.read_text(encoding="utf-8", errors="replace") if failing.is_file() else None,
            alltests.read_text(encoding="utf-8", errors="replace") if alltests.is_file() else None,
            out)
        r.update(replay_failed=failed, replay_passed=passed, replay_names=names[:6])
        if failed > 0:
            r["status"] = "failed"
        elif rc != 0:
            r["status"] = "build_failed"
            r["detail"] = out.strip()[-300:]
        elif not passed:
            r["status"] = "no_tests"
        else:
            r["status"] = "passed"
        return r
    except subprocess.TimeoutExpired:
        return {**r, "status": "timeout"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def render(rows: list[dict]) -> str:
    o = ["# Defects4J patch-replay validation", "",
         "Each row re-grades the run's SOURCE-only patch on a pristine checkout, so "
         "any damage the agent did to its own workdir (dependency stubs, pom edits, "
         "deleted tests, build junk) cannot influence the verdict.", "",
         "| bug | arm | rep | recorded | replay | agree? | replay fail/pass | src files | dropped |",
         "|---|---|---|---|---|---|---|---|---|"]
    disagree = []
    for r in rows:
        rec, rep = r.get("recorded"), r.get("status")
        comparable = rep in ("passed", "failed") and rec in ("passed", "failed")
        agree = "—" if not comparable else ("yes" if rec == rep else "**NO**")
        if comparable and rec != rep:
            disagree.append(r)
        fp = (f"{r.get('replay_failed')}/{r.get('replay_passed')}"
              if r.get("replay_failed") is not None else "—")
        o.append(f"| {r['bug']} | {r.get('arm', '—')} | {r.get('rep', '—')} "
                 f"| {rec or '—'} | {rep} | {agree} | {fp} "
                 f"| {len(r.get('kept') or [])} | {r.get('dropped', '—')} |")
    o.append("")
    if disagree:
        o += ["## Disagreements — the recorded verdict was about the ENVIRONMENT, not the fix", ""]
        for r in disagree:
            o.append(f"- **{r['bug']}** [{r.get('arm', '—')}/{r.get('rep', '—')}]: recorded `{r['recorded']}` "
                     f"({r.get('recorded_failed')} failing) but the same patch replays as "
                     f"`{r['status']}` ({r.get('replay_failed')} failing). "
                     f"Source files: {', '.join(r.get('kept') or []) or '—'}")
            if r.get("replay_names"):
                o.append(f"  - replay failures: " + ", ".join(f"`{n}`" for n in r["replay_names"]))
        o.append("")
    odd = [r for r in rows if r.get("status") not in ("passed", "failed")]
    if odd:
        o += ["## Not replayable (no verdict — inspect these)", ""]
        o += [f"- **{r['bug']}**: {r['status']}" +
              (f" — {r['detail']}" if r.get("detail") else "") for r in odd]
        o.append("")
    return "\n".join(o)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("bugs", nargs="*", help="bug dirs to replay (default: the FAILED runs)")
    ap.add_argument("--root", default="d4j-runs", type=Path)
    ap.add_argument("--all", action="store_true", help="replay every graded run")
    ap.add_argument("--ab", action="store_true",
                    help="replay the A/B tree (runs-ab/): EVERY arm and rep, not just "
                         "the newest — grading one arm only would be worthless")
    ap.add_argument("--timeout", type=int, default=2400, help="per-bug test timeout (s)")
    ap.add_argument("--out", type=Path, help="also write the report here")
    a = ap.parse_args()
    if not a.root.is_dir():
        print(f"no such run root: {a.root}")
        return 2

    dirs = [p for p in sorted(a.root.iterdir()) if p.is_dir() and "-" in p.name]
    if a.bugs:
        want = set(a.bugs)
        dirs = [p for p in dirs if p.name in want]

    if a.ab:
        # Every arm x rep, so rcc and phased are graded by the same yardstick.
        jobs = [(d, rd) for d in dirs for rd in all_runs(d, "runs-ab")]
        if not jobs:
            print("no A/B runs found (expected d4j-runs/<bug>/runs-ab/…) — run run_ab.sh first")
            return 0
        rows = []
        for i, (d, rd) in enumerate(jobs, 1):
            print(f"[{i}/{len(jobs)}] replaying {d.name} {rd.parent.name}/{rd.name} …",
                  flush=True)
            rows.append(replay(d, a.timeout, rundir=rd))
        text = render(rows)
        print("\n" + text)
        if a.out:
            a.out.write_text(text, encoding="utf-8")
            print(f"\n[written to {a.out}]")
        return 0

    if not a.bugs and not a.all:
        # Default: only the sieve's OUTPUT (failed runs) — a full replay is one
        # test suite per bug, i.e. hours. --all when you want the passes checked
        # for the opposite error (a green verdict the patch cannot reproduce).
        keep = []
        for p in dirs:
            rd = _latest_run(p)
            if rd and (_load(rd / "metrics.json") or {}).get("verify_status") == "failed":
                keep.append(p)
        dirs = keep
    if not dirs:
        print("nothing to replay (no FAILED runs; use --all or name bugs explicitly)")
        return 0

    rows = []
    for i, d in enumerate(dirs, 1):
        print(f"[{i}/{len(dirs)}] replaying {d.name} …", flush=True)
        rows.append(replay(d, a.timeout))
    text = render(rows)
    print("\n" + text)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
        print(f"\n[written to {a.out}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
