#!/usr/bin/env python3
"""Summarise the Defects4J cost-to-solve A/B into one paste-able report.

The A/B tree is d4j-runs/<bug>/runs-ab/<exp>/<ts>/<arm>/rep_N/ — dozens of runs whose
logs are far too large to read. This aggregates them into: per-bug cost per arm, the
rcc-vs-baseline delta, a headline median, and the two things that would silently
invalidate the whole comparison —

  * rcc runs that DEGRADED to plain phased (no usable mutation graph). The treatment
    did not happen there, so those bugs must not be counted as "rcc didn't help".
  * cost compared across arms that did not both SOLVE the bug. Time-to-solve is only
    meaningful when both arms actually solved it, so the headline is computed over
    that subset and solve-rate is reported separately.

    python3 scripts/d4j_ab_summary.py --out ab.md
"""
from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from d4j_sieve_summary import _bucket, _changed_files, _load  # noqa: E402

#: The runner logs this when rcc cannot build/focus a graph and falls back to phased.
_DEGRADE_MARKS = ("degrading to plain phased", "no usable mutation graph")


def _degraded(rundir: Path) -> bool:
    log = rundir / "run.log"
    if not log.is_file():
        return False
    text = log.read_text(encoding="utf-8", errors="replace")
    return any(m in text for m in _DEGRADE_MARKS)


def collect(root: Path) -> list[dict]:
    rows = []
    for bugdir in sorted(p for p in root.iterdir() if p.is_dir() and "-" in p.name):
        for mfile in sorted(bugdir.glob("runs-ab/*/*/*/rep_*/metrics.json")):
            rd = mfile.parent
            m = _load(mfile) or {}
            t = _load(rd / "trace.json")
            files = _changed_files(t, rd)
            buckets = {}
            for p, _a, _r in files:
                buckets[_bucket(p)] = buckets.get(_bucket(p), 0) + 1
            rows.append({
                "bug": bugdir.name,
                "arm": rd.parent.name,
                "rep": rd.name,
                "solved": m.get("verify_status") == "passed",
                "status": m.get("verify_status"),
                "failed": m.get("verify_failed_count"),
                "duration": m.get("duration_s"),
                "steps": m.get("n_steps"),
                "tokens": (m.get("tokens_in") or 0) + (m.get("tokens_out") or 0),
                "test_runs": m.get("n_test_runs"),
                "rcc_loop": (m.get("rcc_subset_test_runs") or 0) > 0
                            or m.get("rcc_root_rank") is not None,
                "rcc_subset_runs": m.get("rcc_subset_test_runs"),
                "rcc_root_rank": m.get("rcc_root_rank"),
                "rcc_beta_deg": m.get("rcc_beta_degraded"),
                "rcc_gamma_deg": m.get("rcc_gamma_degraded"),
                "degraded": _degraded(rd),
                "test_edits": buckets.get("test", 0),
                "cheat": [s.get("type") for s in
                          ((m.get("cheating") or {}).get("signals") or [])],
                "error": m.get("error"),
                "rundir": str(rd.relative_to(root)),
            })
    return rows


def _agg(rows: list[dict], key: str) -> float | None:
    vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
    return statistics.mean(vals) if vals else None


def _fmt(v, spec=".0f") -> str:
    return format(v, spec) if isinstance(v, (int, float)) else "—"


def render(rows: list[dict]) -> str:
    bugs = sorted({r["bug"] for r in rows})
    arms = sorted({r["arm"] for r in rows})
    o = ["# Defects4J cost-to-solve A/B — digest", "",
         f"runs: **{len(rows)}** | bugs: {len(bugs)} | arms: {', '.join(arms)} | "
         f"reps/arm: {len({r['rep'] for r in rows})}", ""]

    # ── rcc health: did the treatment actually happen? ────────────────────────
    rcc = [r for r in rows if r["arm"] == "rcc"]
    if rcc:
        deg = [r for r in rcc if r["degraded"]]
        loop = [r for r in rcc if r["rcc_loop"]]
        o += [f"**rcc health:** {len(loop)}/{len(rcc)} runs actually entered the causal "
              f"loop; **{len(deg)} degraded to plain phased** (no usable mutation graph)."
              + (" A degraded run is NOT evidence that rcc didn't help — the treatment "
                 "never ran." if deg else ""), ""]
        if deg:
            o += ["Degraded runs: " + ", ".join(f"`{r['bug']}/{r['rep']}`" for r in deg), ""]

    # ── per-bug, per-arm cost (mean over reps) ────────────────────────────────
    o += ["## Cost per bug (mean over reps)", "",
          "| bug | arm | solved | dur_s | steps | tokens | test runs | loop |",
          "|---|---|---|---|---|---|---|---|"]
    per: dict[tuple[str, str], dict] = {}
    for bug in bugs:
        for arm in arms:
            rs = [r for r in rows if r["bug"] == bug and r["arm"] == arm]
            if not rs:
                continue
            a = {"solved": sum(1 for r in rs if r["solved"]), "n": len(rs),
                 "duration": _agg(rs, "duration"), "steps": _agg(rs, "steps"),
                 "tokens": _agg(rs, "tokens"), "test_runs": _agg(rs, "test_runs"),
                 "degraded": any(r["degraded"] for r in rs),
                 "loop": sum(1 for r in rs if r["rcc_loop"])}
            per[(bug, arm)] = a
            loop = ("—" if arm != "rcc"
                    else ("DEGRADED" if a["degraded"] else f"{a['loop']}/{a['n']}"))
            o.append(f"| {bug} | {arm} | {a['solved']}/{a['n']} | {_fmt(a['duration'])} "
                     f"| {_fmt(a['steps'], '.1f')} | {_fmt(a['tokens'])} "
                     f"| {_fmt(a['test_runs'], '.1f')} | {loop} |")
    o.append("")

    # ── rcc vs baseline ──────────────────────────────────────────────────────
    if "rcc" in arms and "baseline" in arms:
        o += ["## rcc vs baseline (ratio <1 = rcc cheaper)", "",
              "| bug | both solved? | dur ratio | steps ratio | tokens ratio | note |",
              "|---|---|---|---|---|---|"]
        ratios: dict[str, list[float]] = {"duration": [], "steps": [], "tokens": []}
        solve_b = solve_r = 0
        for bug in bugs:
            b, r = per.get((bug, "baseline")), per.get((bug, "rcc"))
            if not b or not r:
                continue
            solve_b += b["solved"] > 0
            solve_r += r["solved"] > 0
            both = b["solved"] > 0 and r["solved"] > 0
            note = []
            if r["degraded"]:
                note.append("rcc DEGRADED — excluded")
            if not both:
                note.append(f"solve differs (base {b['solved']}/{b['n']}, "
                            f"rcc {r['solved']}/{r['n']}) — cost not comparable")
            cells = []
            for k in ("duration", "steps", "tokens"):
                if b[k] and r[k]:
                    ratio = r[k] / b[k]
                    cells.append(f"{ratio:.2f}×")
                    # Only pool a ratio when the comparison is meaningful.
                    if both and not r["degraded"]:
                        ratios[k].append(ratio)
                else:
                    cells.append("—")
            o.append(f"| {bug} | {'yes' if both else 'NO'} | " + " | ".join(cells)
                     + f" | {'; '.join(note)} |")
        o.append("")
        n = len(ratios["duration"])
        o += [f"### Headline (over the {n} bug(s) where BOTH arms solved and rcc ran "
              "its loop)", ""]
        if n:
            for k, label in (("duration", "wall-clock"), ("steps", "steps"),
                             ("tokens", "tokens")):
                v = ratios[k]
                if v:
                    med = statistics.median(v)
                    faster = sum(1 for x in v if x < 1)
                    # Spell the direction out: "0.47× (+53%)" reads as *more*
                    # expensive at a glance, which is the opposite of the finding.
                    word = (f"{(1 - med) * 100:.0f}% CHEAPER" if med < 1
                            else f"{(med - 1) * 100:.0f}% more expensive" if med > 1
                            else "no difference")
                    o.append(f"- **{label}**: median **{med:.2f}×** baseline → "
                             f"**{word}** — rcc cheaper on {faster}/{len(v)} bugs")
            o += ["", f"Solve-rate control: baseline {solve_b}/{len(bugs)}, "
                      f"rcc {solve_r}/{len(bugs)} bugs solved at least once.", ""]
        else:
            o += ["- **No comparable bug**: every pair either differs in solve outcome "
                  "or had rcc degrade. The cost claim cannot be made from this batch.", ""]

    # ── validity ─────────────────────────────────────────────────────────────
    bad = [r for r in rows if r["test_edits"] or r["cheat"] or r["error"]]
    if bad:
        o += ["## Validity flags (per run)", ""]
        for r in bad:
            bits = []
            if r["test_edits"]:
                bits.append(f"edited {r['test_edits']} test file(s)")
            if r["cheat"]:
                bits.append("anti-cheat: " + ", ".join(r["cheat"]))
            if r["error"]:
                bits.append(f"error: {str(r['error'])[:120]}")
            o.append(f"- `{r['bug']}` [{r['arm']}/{r['rep']}]: " + "; ".join(bits))
        o += ["", "Re-grade every arm environment-independently before trusting the "
                  "solve column: `python3 scripts/d4j_replay.py --ab`", ""]
    return "\n".join(o)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default="d4j-runs", type=Path)
    ap.add_argument("--out", type=Path, help="also write the digest here")
    a = ap.parse_args()
    if not a.root.is_dir():
        print(f"no such run root: {a.root}")
        return 2
    rows = collect(a.root)
    if not rows:
        print("no A/B runs found (expected d4j-runs/<bug>/runs-ab/…)")
        return 0
    text = render(rows)
    print(text)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
        print(f"\n[written to {a.out}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
