#!/usr/bin/env python3
"""Collect a Defects4J sieve batch into ONE compact, paste-able digest.

A batch leaves a deep tree (d4j-runs/<P>-<bug>/runs/<exp>/<ts>/<cond>/rep_N/ with
trace.json + metrics.json + changes.patch) whose raw traces are far too large to
read or share — a single trace is tens of thousands of lines. This walks the tree
and emits markdown: the per-bug verdict table, the sieve's actual output (which
bugs the plain agent FAILED = the RCC demo set), anomalies that invalidate a row
(harness crash, bug that doesn't reproduce, no tests executed), and a bounded
per-bug detail block (failing tests, tool-call shape, the agent's closing claim).

    python3 scripts/d4j_sieve_summary.py                       # digest to stdout
    python3 scripts/d4j_sieve_summary.py --out sieve.md        # …and to a file
    python3 scripts/d4j_sieve_summary.py --detail-all          # detail every bug
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

MAX_FAILED_NAMES = 6       # per bug, in the detail block
MAX_TOOLS = 8              # tool-histogram entries
CLAIM_CHARS = 400          # tail of the agent's final message


def _load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def _gems(path: Path) -> dict[str, dict]:
    """gems.csv rows keyed '<project>-<bug>' (tier/triggers/modified_class)."""
    if not path.is_file():
        return {}
    return {f"{r['project']}-{r['bug']}": r for r in csv.DictReader(path.open())}


def _latest_run(bugdir: Path) -> Path | None:
    """Newest rep dir holding a metrics.json (batches may be re-run)."""
    cands = sorted(bugdir.glob("runs/*/*/*/rep_*/metrics.json"),
                   key=lambda p: p.stat().st_mtime)
    return cands[-1].parent if cands else None


def _tool_hist(trace: dict | None) -> Counter:
    c: Counter = Counter()
    for st in (trace or {}).get("steps", []) or []:
        if st.get("kind") == "tool" and st.get("tool_name"):
            c[st["tool_name"]] += 1
    return c


def _final_claim(trace: dict | None) -> str:
    """The agent's last assistant text — its own claim about the fix, which is
    the thing to distrust when it contradicts the defects4j verdict."""
    texts = [st.get("text") or "" for st in (trace or {}).get("steps", []) or []
             if st.get("kind") in ("assistant", "text", "message") and st.get("text")]
    return (texts[-1].strip().replace("\n", " ")[:CLAIM_CHARS]) if texts else ""


def collect(root: Path, gems: dict[str, dict]) -> list[dict]:
    rows = []
    for bugdir in sorted(p for p in root.iterdir() if p.is_dir() and "-" in p.name):
        key = bugdir.name
        g = gems.get(key, {})
        row: dict = {
            "bug": key,
            "tier": g.get("tier", ""),
            "triggers": g.get("triggers", ""),
            "cls": g.get("modified_class", ""),
            "state": "",           # what actually happened to this bug
        }
        # Did the bug reproduce at all? (reference green + buggy tree red)
        base = _load(bugdir / ".verify-baseline.json")
        if base:
            row["repro"] = (base.get("status") == "passed"
                            and (base.get("fixture_failed_count") or 0) > 0)
            row["repro_fail"] = base.get("fixture_failed_count")
        else:
            row["repro"] = None

        rundir = _latest_run(bugdir)
        if rundir is None:
            # No run at all: checkout failed / skipped by run_baseline.sh.
            row["state"] = "SKIPPED (no run — checkout failed?)"
            rows.append(row)
            continue

        m = _load(rundir / "metrics.json") or {}
        t = _load(rundir / "trace.json")
        row.update(
            rundir=str(rundir.relative_to(root)),
            verify=m.get("verify_status"),
            reason=m.get("verify_reason"),
            message=m.get("verify_message"),
            passed=m.get("verify_passed_count"),
            failed=m.get("verify_failed_count"),
            failed_names=m.get("verify_failed_names") or [],
            duration=m.get("duration_s"),
            steps=m.get("n_steps"),
            edits=m.get("n_files_edited"),
            added=m.get("diff_lines_added"),
            removed=m.get("diff_lines_removed"),
            tokens_in=m.get("tokens_in"),
            tokens_out=m.get("tokens_out"),
            similarity=(m.get("cheating") or {}).get("target_similarity"),
            changed=m.get("made_source_changes"),
            finished=m.get("finished"),
            interrupted=m.get("interrupted_reason"),
            error=m.get("error"),
            tools=_tool_hist(t),
            claim=_final_claim(t),
        )
        # State is the honest one-word verdict. Crash and non-reproducing come
        # FIRST: a crashed run has no grade, and a green verdict on a bug whose
        # buggy tree already passed grades nothing — neither may be read as a
        # real sieve result.
        if row["error"] or row["interrupted"] == "error":
            row["state"] = "CRASHED (no verdict)"
        elif row.get("repro") is False:
            row["state"] = "INVALID (bug does not reproduce)"
        elif row["verify"] == "passed":
            row["state"] = "passed (agent solved it)"
        elif row["verify"] == "failed":
            row["state"] = "FAILED → RCC candidate"
        elif row["verify"] in (None, "skipped"):
            row["state"] = f"no verdict (verify={row['verify']})"
        else:
            row["state"] = f"{row['verify']} ({row.get('reason')})"
        rows.append(row)
    return rows


def render(rows: list[dict], detail_all: bool) -> str:
    o: list[str] = ["# Defects4J baseline sieve — digest", ""]
    n = len(rows)
    cand = [r for r in rows if r["state"].startswith("FAILED")]
    solved = [r for r in rows if r["state"].startswith("passed")]
    crashed = [r for r in rows if r["state"].startswith("CRASHED")]
    skipped = [r for r in rows if r["state"].startswith("SKIPPED")]
    invalid = [r for r in rows if r["state"].startswith("INVALID")]
    other = [r for r in rows if r not in cand + solved + crashed + skipped + invalid]
    o += [f"bugs: **{n}** | RCC candidates (baseline failed): **{len(cand)}** | "
          f"agent solved: {len(solved)} | crashed: {len(crashed)} | "
          f"skipped: {len(skipped)} | no-repro: {len(invalid)} | other: {len(other)}", ""]

    o += ["## Verdicts", "",
          "| bug | tier | trig | repro | state | fail/pass | steps | edits | +/- | sim | dur_s |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        repro = {True: "yes", False: "NO", None: "?"}[r.get("repro")]
        fp = (f"{r.get('failed')}/{r.get('passed')}"
              if r.get("failed") is not None else "—")
        pm = (f"+{r.get('added')}/-{r.get('removed')}"
              if r.get("added") is not None else "—")
        sim = f"{r['similarity']:.2f}" if isinstance(r.get("similarity"), float) else "—"
        dur = f"{r['duration']:.0f}" if isinstance(r.get("duration"), float) else "—"
        o.append(f"| {r['bug']} | {r.get('tier','')} | {r.get('triggers','')} | {repro} "
                 f"| {r['state']} | {fp} | {r.get('steps','—')} | {r.get('edits','—')} "
                 f"| {pm} | {sim} | {dur} |")
    o.append("")

    if cand:
        o += ["## RCC demo set (baseline FAILED — the sieve's output)", ""]
        o += [f"- **{r['bug']}** ({r.get('tier')}, {r.get('triggers')} triggers) — "
              f"{r.get('message') or r.get('reason')} | target `{r.get('cls')}`"
              for r in cand]
        o.append("")

    bad = crashed + skipped + invalid + other
    seen, uniq = set(), []
    for r in bad:
        if r["bug"] not in seen:
            seen.add(r["bug"]); uniq.append(r)
    if uniq:
        o += ["## Anomalies (rows that are NOT a valid sieve result)", ""]
        for r in uniq:
            why = r["state"]
            if r.get("repro") is False:
                why += " | bug does NOT reproduce (fixture green) — row is meaningless"
            if r.get("error"):
                why += f" | {str(r['error'])[:200]}"
            o.append(f"- **{r['bug']}**: {why}")
        o.append("")

    show = rows if detail_all else [r for r in rows if r.get("rundir")
                                    and not r["state"].startswith("passed")]
    if show:
        o += ["## Per-bug detail", ""]
        for r in show:
            o += [f"### {r['bug']} — {r['state']}"]
            if r.get("message"):
                o.append(f"- verify: `{r.get('verify')}` / {r.get('reason')} — {r['message']}")
            if r.get("failed_names"):
                names = list(r["failed_names"])[:MAX_FAILED_NAMES]
                o.append(f"- failing ({len(r['failed_names'])} listed): "
                         + ", ".join(f"`{x}`" for x in names))
            if r.get("tools"):
                top = ", ".join(f"{k}×{v}" for k, v in r["tools"].most_common(MAX_TOOLS))
                o.append(f"- tools: {top}")
            o.append(f"- edits: {r.get('edits')} files, +{r.get('added')}/-{r.get('removed')} | "
                     f"tokens in/out: {r.get('tokens_in')}/{r.get('tokens_out')} | "
                     f"finished={r.get('finished')} stop={r.get('interrupted')}")
            if r.get("claim"):
                o.append(f"- agent's final claim: \"{r['claim']}\"")
            if r.get("rundir"):
                o.append(f"- run: `{r['rundir']}`")
            o.append("")
    return "\n".join(o)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default="d4j-runs", type=Path)
    ap.add_argument("--gems", default="experiments/defects4j/gems.csv", type=Path)
    ap.add_argument("--out", type=Path, help="also write the digest here")
    ap.add_argument("--detail-all", action="store_true",
                    help="detail every bug, not just the non-passing ones")
    a = ap.parse_args()
    if not a.root.is_dir():
        print(f"no such run root: {a.root}")
        return 2
    text = render(collect(a.root, _gems(a.gems)), a.detail_all)
    print(text)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
        print(f"\n[written to {a.out}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
