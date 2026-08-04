#!/usr/bin/env python3
"""Which repositories can measure anything — the memorisation probe's verdict.

jackson-core turned out to be reproduced VERBATIM: median similarity to the reference
fix was 1.00 even with the tests hidden, so every number measured recall, not
problem-solving. This scans the probe roots and answers one question per repository:
is the model deriving the fix, or recalling it?

`similarity` is the agent's final target method vs the REFERENCE fix, comment- and
format-insensitive (abench's own cheating detector computes it). >=0.98 means
"identical bar trivia" — the model had seen this commit.

    python3 scripts/swe_probe_summary.py            # every swe-probe-* root
    python3 scripts/swe_probe_summary.py --roots swe-probe-fastjson2
"""
from __future__ import annotations

import argparse
import glob
import json
import statistics
from pathlib import Path

VERBATIM = 0.98


def _load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def is_dead(m: dict) -> bool:
    """A run that never touched the code, so its similarity is meaningless.

    This matters more here than anywhere else. A proxy-killed session leaves the
    checkout untouched, so `target_similarity` is measured against the BUGGY source
    and comes out low — exactly the value that reads as "the model is deriving, not
    recalling". Counting those would turn a memorised repository into a recommended
    one. On hidden-test fixtures they also grade as verify=passed, because the suite
    is green by design, so the verdict cannot filter them either.
    """
    return bool(m.get("n_service_errors") or m.get("error")
                or m.get("n_steps") == 0 or m.get("tokens_in") == 0)


def scan(root: Path) -> dict:
    sims, solved, runs, dead = [], 0, 0, 0
    for mf in root.glob("*/runs/*/*/*/rep_*/metrics.json"):
        m = _load(mf) or {}
        runs += 1
        if is_dead(m):
            dead += 1
            continue
        s = (m.get("cheating") or {}).get("target_similarity")
        if isinstance(s, (int, float)):
            sims.append(float(s))
        if m.get("verify_status") == "passed":
            solved += 1
    return {"repo": root.name.replace("swe-probe-", ""), "runs": runs, "sims": sims,
            "solved": solved, "dead": dead, "live": runs - dead}


def verdict(sims: list[float]) -> str:
    """The probe's whole point: say plainly whether this repo can measure anything."""
    if not sims:
        return "no similarity data (needs target_file + a completed run)"
    med = statistics.median(sims)
    verb = sum(1 for s in sims if s >= VERBATIM)
    if med >= VERBATIM:
        return "MEMORISED — the fix is reproduced verbatim; cannot measure solving"
    if verb >= len(sims) / 2:
        return "mostly memorised — half the runs are verbatim"
    return "USABLE — the model is deriving, not recalling"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--roots", nargs="*", help="probe roots (default: swe-probe-*)")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    roots = [Path(r) for r in (a.roots or sorted(glob.glob("swe-probe-*")))]
    roots = [r for r in roots if r.is_dir()]
    if not roots:
        print("no probe roots found — run: ./scripts/swe.sh probe")
        return 1

    rows = [scan(r) for r in roots]
    o = ["# Memorisation probe", "",
         "| repo | runs (live/total) | median similarity | verbatim (>=0.98) | "
         "workdir-passed | verdict |",
         "|---|---|---|---|---|---|"]
    for r in rows:
        sims = r["sims"]
        med = f"{statistics.median(sims):.2f}" if sims else "—"
        verb = f"{sum(1 for s in sims if s >= VERBATIM)}/{len(sims)}" if sims else "—"
        o.append(f"| {r['repo']} | {r['live']}/{r['runs']} | {med} | {verb} | "
                 f"{r['solved']}/{r['live']} | {verdict(sims)} |")
    o += ["",
          "`workdir-passed` is NOT a solve rate on hidden-test fixtures — it only says "
          "the run broke nothing. For the real verdict run "
          "`python3 scripts/d4j_replay.py --root <probe-root> --ab --runs-dir runs`, "
          "which applies the withheld tests.", ""]
    bad = [r for r in rows if r["dead"]]
    if bad:
        o += ["Dead runs EXCLUDED from every column above (provider error, crash, or\n"
              "zero steps — they never touched the code, so their similarity would be\n"
              "measured against the buggy source and read as 'not memorised'): "
              + ", ".join(f"{r['repo']} ({r['dead']}/{r['runs']})" for r in bad), ""]
    # Match the per-row verdict exactly: a repo where half the runs are verbatim is
    # "mostly memorised" and must not be recommended just because its MEDIAN dipped.
    usable = [r for r in rows if r["sims"]
              and statistics.median(r["sims"]) < VERBATIM
              and sum(1 for s in r["sims"] if s >= VERBATIM) < len(r["sims"]) / 2]
    o += [("**Next:** measure rcc on " + ", ".join(r["repo"] for r in usable)
           + " — the model is not just recalling there.") if usable else
          "**No usable repository in this probe.** Every one is reproduced verbatim, so "
          "none of them can measure problem-solving. Next lever: instances newer than "
          "the model's training cutoff, or a stronger/weaker model to shift the recall "
          "boundary.", ""]
    text = "\n".join(o)
    print(text)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
        print(f"[written to {a.out}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
