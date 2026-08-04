#!/usr/bin/env python3
"""Collect the runs that are actually BROKEN into one paste-able file.

Every run writes run.log / debug.log / error.log under its own rep dir, so diagnosing
a batch means opening dozens of files — and the console scrollback is usually gone by
then.

The verdict comes from abench's own trailer lines, which already carry the counters it
computed:

    [abench] opencode returncode=0 interrupted=None service_errors=0 rate_limits=0
    [abench] changes: +12/-6 across 1 file(s)
    [abench] result: finished=True reason=None steps=105 ... verify=passed

Free-text grepping does NOT work here and the first version of this script proved it:
`rate.?limit` matches the healthy line `rate_limits=0`, and bare `429`/`407`/`502`
match token counts and git hashes, so 83 of 117 perfectly good runs were reported as
rate-limited. Patterns are now used only for faults abench does not summarise, are
anchored to real message text, and never read the agent's own `[llm ]` prose — which
quotes things like "BUILD FAILURE" while describing what it fixed.

A failed verify is an OUTCOME, not a fault: it is counted separately and never
inflates the broken-run count.

    python3 scripts/swe_logs.py                       # every run root here
    python3 scripts/swe_logs.py --roots swe-probe-dubbo --out logs.md
"""
from __future__ import annotations

import argparse
import glob
import re
from pathlib import Path

TAIL = 25          # lines of log kept per broken run
MAX_RUNS = 30      # keep the report paste-able

#: abench's own summary lines — ground truth, already counted by the harness.
_OPENCODE = re.compile(r"\[abench\] opencode returncode=(-?\d+) interrupted=(\S+) "
                       r"service_errors=(\d+) rate_limits=(\d+)")
_RESULT = re.compile(r"\[abench\] result: finished=(\S+) reason=(\S+) steps=(\d+) "
                     r"tokens_in=(\d+) tokens_out=(\d+) verify=(\S+)")
_CHANGES = re.compile(r"\[abench\] changes: \+(\d+)/-(\d+) across (\d+) file")

#: Faults abench does not summarise. Anchored to real message text — no bare numbers,
#: because a status code as a bare integer matches hashes, token counts and timestamps.
SIGNATURES = {
    "filesystem I/O": re.compile(
        r"Input/output error|Structure needs cleaning|No space left on device|"
        r"Stale file handle|Read-only file system"),
    "git failure": re.compile(r"fatal: unable to (read|write|access)|index\.lock|"
                              r"could not lock config|fatal: .*\.git/"),
    "proxy/auth": re.compile(r"Proxy Authentication Required|\b407 Proxy|"
                             r"401 Unauthorized|403 Forbidden"),
    "rate limited": re.compile(r"Too Many Requests|\b429\b[^\d]*(Too Many|rate)|"
                               r'"statusCode":\s*429'),
    "timeout": re.compile(r"TimeoutExpired|command timed out|timed out after"),
}
#: The agent narrates its own work; its prose must never be scanned for faults.
_AGENT_PROSE = re.compile(r"^\s*\[(llm|ERR)\s*\]")


def _read(p: Path, limit: int = 400_000) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError as exc:
        return f"<<could not read {p}: {exc}>>"


def scan_run(rundir: Path) -> dict | None:
    """A BROKEN run's evidence, or None when the run is sound.

    "Broken" means the run cannot be counted as a fair measurement: the provider
    errored, the harness never produced a result, or the environment failed under it.
    """
    text = ""
    for name in ("run.log", "debug.log"):
        f = rundir / name
        if f.is_file():
            text += _read(f)
    if not text and not (rundir / "error.log").is_file():
        return None

    faults: list[str] = []
    oc = _OPENCODE.search(text)
    res = _RESULT.search(text)

    if oc:
        rc, interrupted, service_errors, rate_limits = oc.groups()
        if int(service_errors):
            faults.append(f"provider error x{service_errors}")
        if int(rate_limits):
            faults.append(f"rate limited x{rate_limits}")
        if int(rc):
            faults.append(f"opencode exit {rc}")
        if interrupted not in ("None", "False"):
            faults.append(f"interrupted={interrupted}")
    if res:
        finished, reason, steps, t_in, _t_out, _verify = res.groups()
        if finished != "True":
            faults.append(f"unfinished (reason={reason})")
        if steps == "0" or t_in == "0":
            # No steps and no input tokens: the session never got off the ground, so
            # whatever verdict it carries is about the untouched checkout.
            faults.append("session never ran (0 steps)")
    elif oc:
        faults.append("no result line (crashed after the agent)")
    else:
        faults.append("no abench summary (crashed early or still running)")

    # Environment faults, read only from harness/tool output — never the agent's prose.
    ops = "\n".join(ln for ln in text.splitlines() if not _AGENT_PROSE.match(ln))
    for label, rx in SIGNATURES.items():
        if rx.search(ops):
            faults.append(label)

    if (rundir / "error.log").is_file():
        faults.append("crashed")
    if not faults:
        return None

    ch = _CHANGES.search(text)
    return {"rundir": rundir, "faults": sorted(set(faults)),
            "verify": res.group(6) if res else None,
            "changes": ch.group(0).replace("[abench] ", "") if ch else None,
            "error": _read(rundir / "error.log", 4000)
                     if (rundir / "error.log").is_file() else None,
            "tail": "\n".join(text.strip().splitlines()[-TAIL:])}


def tally_outcomes(rundirs: list[Path]) -> dict:
    """Verify verdicts across ALL runs — an outcome, deliberately not a fault."""
    out = {"passed": 0, "failed": 0, "unknown": 0}
    for d in rundirs:
        text = ""
        for name in ("run.log", "debug.log"):
            f = d / name
            if f.is_file():
                text += _read(f)
        m = _RESULT.search(text)
        out[m.group(6) if m and m.group(6) in out else "unknown"] += 1
    return out


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
    rundirs.sort()
    broken = [r for r in (scan_run(d) for d in rundirs) if r]
    outcomes = tally_outcomes(rundirs)

    o = ["# Broken runs", "",
         f"roots: {', '.join(str(r) for r in roots)}", "",
         f"- runs scanned: **{len(rundirs)}**",
         f"- broken (cannot be counted as a measurement): **{len(broken)}**",
         f"- verify outcomes across all runs: {outcomes['passed']} passed / "
         f"{outcomes['failed']} failed / {outcomes['unknown']} unknown",
         "",
         "A failed verify is an outcome, not a fault — it is listed above and never "
         "counted as broken.", ""]
    if not broken:
        o += ["No run shows a provider error, a missing result, or an environment "
              "fault.", ""]
    else:
        tally: dict[str, int] = {}
        for r in broken:
            for f in r["faults"]:
                key = re.sub(r" x\d+$", "", f)
                tally[key] = tally.get(key, 0) + 1
        o += ["| fault | runs |", "|---|---|"]
        o += [f"| {k} | {v} |" for k, v in sorted(tally.items(), key=lambda x: -x[1])]
        o.append("")
        for r in broken[:MAX_RUNS]:
            o += [f"### `{r['rundir']}`",
                  f"faults: {', '.join(r['faults'])}"
                  + (f" | verify={r['verify']}" if r["verify"] else "")
                  + (f" | {r['changes']}" if r["changes"] else ""), ""]
            if r["error"]:
                o += ["```", r["error"].strip()[-1500:], "```"]
            if r["tail"]:
                o += ["<details><summary>log tail</summary>", "", "```",
                      r["tail"][-2500:], "```", "</details>", ""]
        if len(broken) > MAX_RUNS:
            o.append(f"_…and {len(broken) - MAX_RUNS} more (capped for readability)_")
    text = "\n".join(o)
    print(text)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
        print(f"\n[written to {a.out}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
