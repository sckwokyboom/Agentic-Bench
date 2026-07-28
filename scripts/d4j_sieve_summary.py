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
MAX_FILES = 6              # changed-file entries (largest edits first)
MAX_EVIDENCE = 6           # anti-cheat evidence snippets per bug
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


#: Build/generated output that is NOT a source change. A "fix" whose diff is
#: mostly these is a polluted measurement, not a 500-file edit.
_BUILD_HINTS = ("build/", "target/", "dist/", "out/", "bin/", "classes/",
                ".class", ".jar", ".war", "/all_tests", "/failing_tests",
                "all_tests", "failing_tests", ".defects4j.config")


def _bucket(path: str) -> str:
    """Classify a changed path. 'test' is the validity-critical one: the task
    forbids editing tests, and a green verdict reached by weakening a test is a
    false pass, not a fix."""
    p = path.replace("\\", "/")
    low = p.lower()
    if any(h in low for h in _BUILD_HINTS):
        return "build"
    if "src/test" in low or "/test/" in low or low.startswith("test/"):
        return "test"
    if p.rsplit("/", 1)[-1].startswith("Test") or p.endswith(("Test.java", "Tests.java")):
        return "test"
    if p.endswith(".java"):
        return "src"
    return "other"


def _changed_files(trace: dict | None, rundir: Path) -> list[tuple[str, int, int]]:
    """[(path, added, removed)] — from the trace's final_diff_summary, falling
    back to parsing changes.patch headers when the summary is absent."""
    fds = ((trace or {}).get("final_diff_summary") or {}).get("files") or []
    out = [(f.get("path", ""), f.get("added") or 0, f.get("removed") or 0)
           for f in fds if f.get("path")]
    if out:
        return out
    patch = rundir / "changes.patch"
    if patch.is_file():
        for ln in patch.read_text(encoding="utf-8", errors="replace").splitlines():
            if ln.startswith("diff --git "):
                seg = ln[len("diff --git "):].split(" b/")
                if len(seg) == 2:
                    out.append((seg[1].strip().strip('"'), 0, 0))
    return out


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
            # No run at all. Distinguish "never attempted" (the generator made the
            # dir but this batch never ran the bug — e.g. a tier filter) from
            # "checkout produced a tree but abench never ran it": conflating them
            # invents a checkout failure that may not have happened.
            if (bugdir / "checkout").is_dir():
                row["state"] = "NOT RUN (checkout present, no abench run)"
            else:
                row["state"] = "NOT ATTEMPTED (no checkout — filtered out or checkout failed)"
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
            cheat_verdict=(m.get("cheating") or {}).get("verdict"),
            cheat_signals=[s.get("type") for s in
                           ((m.get("cheating") or {}).get("signals") or [])],
            # Evidence, not just the label: 'outside_workdir' is fatal if the path
            # is the reference tree (the FIXED source sits next to the checkout)
            # and harmless if it is a JDK source file. Same for vcs_history — the
            # workdir's git is re-inited with one commit, but a Defects4J checkout
            # carries pre-fix/post-fix TAGS, so which repo was queried decides it.
            cheat_evidence=[(s.get("type"), e)
                            for s in ((m.get("cheating") or {}).get("signals") or [])
                            for e in (s.get("evidence") or [])],
            changed=m.get("made_source_changes"),
            finished=m.get("finished"),
            interrupted=m.get("interrupted_reason"),
            error=m.get("error"),
            tools=_tool_hist(t),
            claim=_final_claim(t),
        )
        files = _changed_files(t, rundir)
        buckets: Counter = Counter()
        for path, add, rem in files:
            buckets[_bucket(path)] += 1
        row["files"] = files
        row["buckets"] = buckets
        # Validity flags — reasons a row must not be trusted at face value.
        flags = []
        if buckets.get("test"):
            flags.append(f"EDITED {buckets['test']} TEST FILE(S) — verdict may be a false pass")
        if buckets.get("build"):
            flags.append(f"{buckets['build']} build/generated path(s) in the diff "
                         "(measurement pollution, not a fix)")
        # NOTE: a missing target_similarity is a run-wide CONFIG fact (the baseline
        # yaml sets no target_file), not a per-bug finding — flagging every row with
        # it buries the real signals. Reported once, globally, in render().
        if row.get("cheat_verdict") == "suspicious":
            flags.append(f"anti-cheat: {', '.join(row['cheat_signals']) or 'suspicious'}")
        if row.get("verify") == "passed" and not row.get("changed"):
            flags.append("verdict passed but made_source_changes=False — nothing was fixed")
        row["flags"] = flags
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
    norun = [r for r in rows if r["state"].startswith(("NOT RUN", "NOT ATTEMPTED"))]
    invalid = [r for r in rows if r["state"].startswith("INVALID")]
    other = [r for r in rows if r not in cand + solved + crashed + norun + invalid]
    flagged = [r for r in solved if r.get("flags")]
    o += [f"bugs: **{n}** | ran: **{n - len(norun)}** | RCC candidates (baseline failed): "
          f"**{len(cand)}** | agent solved: {len(solved)} "
          f"(**{len(flagged)} with validity flags**) | crashed: {len(crashed)} | "
          f"not run: {len(norun)} | no-repro: {len(invalid)} | other: {len(other)}", ""]

    o += ["## Verdicts", "",
          "| bug | tier | trig | repro | state | fail/pass | steps | src/test/build | +/- | sim | dur_s |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        repro = {True: "yes", False: "NO", None: "?"}[r.get("repro")]
        fp = (f"{r.get('failed')}/{r.get('passed')}"
              if r.get("failed") is not None else "—")
        pm = (f"+{r.get('added')}/-{r.get('removed')}"
              if r.get("added") is not None else "—")
        sim = f"{r['similarity']:.2f}" if isinstance(r.get("similarity"), float) else "—"
        dur = f"{r['duration']:.0f}" if isinstance(r.get("duration"), float) else "—"
        b = r.get("buckets") or Counter()
        mix = (f"{b.get('src',0)}/{b.get('test',0)}/{b.get('build',0)}"
               + (f"+{b['other']}?" if b.get("other") else "")) if b else "—"
        if b.get("test"):
            mix = "**" + mix + "**"          # test edits: the row to distrust
        o.append(f"| {r['bug']} | {r.get('tier','')} | {r.get('triggers','')} | {repro} "
                 f"| {r['state']} | {fp} | {r.get('steps','—')} | {mix} "
                 f"| {pm} | {sim} | {dur} |")
    o += ["", "`src/test/build` = changed files by kind. **test>0 means the agent edited "
          "tests** — the task forbids it and a green verdict may be a false pass.", ""]

    ran = [r for r in rows if r.get("rundir")]
    if ran and all(r.get("similarity") is None for r in ran):
        o += ["> **Run-wide:** no `target_similarity` on any row — the baseline yaml "
              "sets no `target_file`, so the `output_matches_original` anti-cheat "
              "signal was OFF for the whole batch.", ""]

    if flagged:
        o += ["## Validity flags on 'solved' rows (verify before trusting these)", ""]
        for r in flagged:
            o.append(f"- **{r['bug']}**: " + "; ".join(r["flags"]))
        o.append("")

    if cand:
        o += ["## RCC demo set (baseline FAILED — the sieve's output)", ""]
        o += [f"- **{r['bug']}** ({r.get('tier')}, {r.get('triggers')} triggers) — "
              f"{r.get('message') or r.get('reason')} | target `{r.get('cls')}`"
              for r in cand]
        o.append("")

    bad = crashed + norun + invalid + other
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

    # Detail the non-passing rows AND any 'solved' row carrying a validity flag —
    # an unexamined flagged pass is exactly what would corrupt the demo set.
    show = rows if detail_all else [
        r for r in rows if r.get("rundir")
        and (not r["state"].startswith("passed") or r.get("flags"))]
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
            if r.get("flags"):
                o.append("- ⚠ " + "; ".join(r["flags"]))
            for kind, snippet in (r.get("cheat_evidence") or [])[:MAX_EVIDENCE]:
                o.append(f"  - evidence[{kind}]: `{snippet}`")
            files = r.get("files") or []
            if files:
                # Rank by MEANING, not size: a test edit is the finding, and a real
                # source edit must not be buried under hundreds of build artifacts.
                order = {"test": 0, "src": 1, "other": 2, "build": 3}
                top = sorted(files, key=lambda f: (order[_bucket(f[0])],
                                                   -(f[1] + f[2])))[:MAX_FILES]
                o.append(f"- changed files ({len(files)}): " + ", ".join(
                    f"`{p}` (+{a}/-{d}, {_bucket(p)})" for p, a, d in top))
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
