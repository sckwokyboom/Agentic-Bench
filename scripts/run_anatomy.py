#!/usr/bin/env python3
"""Anatomy of a run batch: where the wall-clock went, and how the agent got its wins.

Two questions the aggregate digests cannot answer:

  1. WHY is one arm slower? Split the wall-clock into tool execution (with test runs
     called out — the expensive unit) and model latency, per arm, and diff them.
  2. WHY is the solve rate so high? Report the signals that distinguish "solved the
     bug" from "recalled the fix": similarity to the reference, how fast the agent
     located the target file, and how much of the work happened before any test ran.

TIMING SOURCE: events.jsonl, not trace.json. The trace stamps a tool_result at the
same instant as its tool_call (21 real test runs summed to 0.1s), so trace timestamps
CANNOT separate waiting-for-the-model from running-tests. The event stream carries
state.time.{start,end} per tool, which is real.

    python3 scripts/run_anatomy.py d4j-runs --runs-dir runs-ab --out anatomy.md
    python3 scripts/run_anatomy.py swe-runs --runs-dir runs
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from d4j_sieve_summary import _changed_files, _load  # noqa: E402

#: Commands that run a build/test suite — the expensive unit of an agent loop.
_TEST_CMD = re.compile(r"\b(gradlew|mvn|mvnw|ant|defects4j)\b")


def _events(rundir: Path) -> list[dict]:
    f = rundir / "events.jsonl"
    if not f.is_file():
        return []
    out = []
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue                      # a truncated tail must not lose the rest
    return out


def time_split(rundir: Path, wall: float | None) -> dict:
    """{tool_s, test_s, n_test, model_s, by_tool} from the event stream."""
    by_tool: Counter = Counter()
    tool_s = test_s = 0.0
    n_test = 0
    spans: list[tuple[float, float]] = []
    for ev in _events(rundir):
        if ev.get("type") != "tool_use":
            continue
        part = ev.get("part") or {}
        state = part.get("state") or {}
        t = state.get("time") or {}
        if not (t.get("start") and t.get("end")):
            continue
        dur = (t["end"] - t["start"]) / 1000.0
        if dur < 0:
            continue
        name = part.get("tool") or "?"
        by_tool[name] += dur
        tool_s += dur
        spans.append((t["start"], t["end"]))
        cmd = json.dumps(state.get("input") or {})
        if _TEST_CMD.search(cmd):
            test_s += dur
            n_test += 1
    # Model latency is what the wall-clock has left once tool execution is removed.
    # Reported as a residual, not measured directly — agent overhead lands here too.
    model_s = max((wall or 0) - tool_s, 0.0) if wall else None
    return {"tool_s": tool_s, "test_s": test_s, "n_test": n_test,
            "model_s": model_s, "by_tool": by_tool, "events": bool(spans)}


def localization(trace: dict | None, target: str | None) -> dict:
    """How quickly the agent got to the file the gold fix changes.

    A run that opens the target file in its first couple of steps did not search for
    it — either the issue text names it, or the model already knew. That is the
    signature worth separating from genuine debugging.
    """
    out = {"first_touch_step": None, "steps_before_first_test": None,
           "first_edit_is_target": None, "n_edits": 0}
    if not trace:
        return out
    steps = trace.get("steps") or []
    tgt = (target or "").split("/")[-1]
    seen_test = False
    for i, s in enumerate(steps):
        if s.get("kind") != "tool_call":
            continue
        args = json.dumps(s.get("tool_args") or {})
        name = (s.get("tool_name") or "").lower()
        if tgt and out["first_touch_step"] is None and tgt in args:
            out["first_touch_step"] = i
        if not seen_test and name == "bash" and _TEST_CMD.search(args):
            out["steps_before_first_test"] = i
            seen_test = True
        if name in ("edit", "write", "patch"):
            out["n_edits"] += 1
            if out["first_edit_is_target"] is None and tgt:
                out["first_edit_is_target"] = tgt in args
    return out


def collect(root: Path, runs_dir: str) -> list[dict]:
    rows = []
    for inst in sorted(p for p in root.iterdir() if p.is_dir()):
        for mfile in sorted(inst.glob(f"{runs_dir}/*/*/*/rep_*/metrics.json")):
            rd = mfile.parent
            m = _load(mfile) or {}
            t = _load(rd / "trace.json")
            wall = m.get("duration_s")
            target = None
            y = inst / "experiment.yaml"
            if y.is_file():
                mt = re.search(r"^target_file:\s*(\S+)", y.read_text(errors="replace"), re.M)
                target = mt.group(1) if mt else None
            files = _changed_files(t, rd)
            rows.append({
                "inst": inst.name, "arm": rd.parent.name, "rep": rd.name,
                "solved": m.get("verify_status") == "passed",
                "wall": wall, "steps": m.get("n_steps"),
                "tokens": (m.get("tokens_in") or 0) + (m.get("tokens_out") or 0),
                "similarity": (m.get("cheating") or {}).get("target_similarity"),
                "cheat": [s.get("type") for s in
                          ((m.get("cheating") or {}).get("signals") or [])],
                "n_files": len(files),
                "added": m.get("diff_lines_added"), "removed": m.get("diff_lines_removed"),
                **time_split(rd, wall),
                **localization(t, target),
            })
    return rows


def _med(vals):
    vals = [v for v in vals if isinstance(v, (int, float))]
    return statistics.median(vals) if vals else None


def _f(v, spec=".0f"):
    return format(v, spec) if isinstance(v, (int, float)) else "—"


def render(rows: list[dict]) -> str:
    arms = sorted({r["arm"] for r in rows})
    o = ["# Run anatomy", "",
         f"runs: **{len(rows)}** | arms: {', '.join(arms)}", ""]
    no_ev = [r for r in rows if not r["events"]]
    if no_ev:
        o += [f"> {len(no_ev)}/{len(rows)} runs have no usable event stream — their "
              "tool/model split is unavailable (shown as —).", ""]

    # ── 1. where the time went ───────────────────────────────────────────────
    o += ["## 1. Where the wall-clock went (median per arm)", "",
          "| arm | runs | wall_s | tool_s | of which tests | test runs | model_s (residual) | steps |",
          "|---|---|---|---|---|---|---|---|"]
    per = {}
    for a in arms:
        rs = [r for r in rows if r["arm"] == a]
        per[a] = {k: _med([r[k] for r in rs]) for k in
                  ("wall", "tool_s", "test_s", "n_test", "model_s", "steps")}
        p = per[a]
        o.append(f"| {a} | {len(rs)} | {_f(p['wall'])} | {_f(p['tool_s'])} "
                 f"| {_f(p['test_s'])} | {_f(p['n_test'], '.1f')} | {_f(p['model_s'])} "
                 f"| {_f(p['steps'], '.1f')} |")
    o.append("")
    if "rcc" in per and "baseline" in per:
        b, r = per["baseline"], per["rcc"]
        o += ["### What the extra time is made of", ""]
        for key, label in (("wall", "wall-clock"), ("tool_s", "tool execution"),
                           ("test_s", "…of that, test suites"), ("model_s", "model latency"),
                           ("n_test", "test-suite runs"), ("steps", "steps")):
            if b.get(key) and r.get(key):
                d = r[key] - b[key]
                o.append(f"- **{label}**: {_f(b[key], '.1f')} → {_f(r[key], '.1f')} "
                         f"({d:+.1f}, {r[key] / b[key]:.2f}×)")
        o += ["", "Model latency is a RESIDUAL (wall − measured tool time), so agent and "
                  "controller overhead land there too. A gap that shows up mostly in "
                  "*tool* time means the loop ran more suites; mostly in the residual "
                  "means it made more model calls.", ""]

    # ── 2. how the wins were obtained ────────────────────────────────────────
    o += ["## 2. How the solved runs were solved", "",
          "| arm | solved | median similarity | ≥0.98 (verbatim) | median steps→target | "
          "target touched first 3 steps | median steps→first test | median edits |",
          "|---|---|---|---|---|---|---|---|"]
    for a in arms:
        rs = [r for r in rows if r["arm"] == a]
        sim = [r["similarity"] for r in rs if isinstance(r["similarity"], float)]
        verbatim = sum(1 for s in sim if s >= 0.98)
        fast = sum(1 for r in rs
                   if isinstance(r["first_touch_step"], int) and r["first_touch_step"] <= 3)
        o.append(f"| {a} | {sum(1 for r in rs if r['solved'])}/{len(rs)} "
                 f"| {_f(_med(sim), '.2f')} | {verbatim}/{len(sim) or '—'} "
                 f"| {_f(_med([r['first_touch_step'] for r in rs]), '.1f')} "
                 f"| {fast}/{len(rs)} "
                 f"| {_f(_med([r['steps_before_first_test'] for r in rs]), '.1f')} "
                 f"| {_f(_med([r['n_edits'] for r in rs]), '.1f')} |")
    o += ["", "`similarity` is the agent's final method vs the REFERENCE fix "
              "(comment/format-insensitive). A median near 1.0, or the target opened "
              "within the first few steps without searching, points at recall rather "
              "than derivation — the axis that separates a real solve rate from a "
              "memorised one.", ""]

    # ── per-instance detail: the outliers are the interesting ones ────────────
    o += ["## Per-instance (median over reps)", "",
          "| instance | arm | solved | wall_s | tests | sim | steps→target |",
          "|---|---|---|---|---|---|---|"]
    for inst in sorted({r["inst"] for r in rows}):
        for a in arms:
            rs = [r for r in rows if r["inst"] == inst and r["arm"] == a]
            if not rs:
                continue
            o.append(f"| {inst} | {a} | {sum(1 for r in rs if r['solved'])}/{len(rs)} "
                     f"| {_f(_med([r['wall'] for r in rs]))} "
                     f"| {_f(_med([r['n_test'] for r in rs]), '.1f')} "
                     f"| {_f(_med([r['similarity'] for r in rs]), '.2f')} "
                     f"| {_f(_med([r['first_touch_step'] for r in rs]), '.1f')} |")
    o.append("")

    tools: Counter = Counter()
    for r in rows:
        tools.update(r["by_tool"])
    if tools:
        o += ["## Tool time overall (seconds)", "",
              ", ".join(f"`{k}` {v:.0f}s" for k, v in tools.most_common(8)), ""]
    return "\n".join(o)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default="d4j-runs", type=Path)
    ap.add_argument("--runs-dir", default="runs-ab")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    if not a.root.is_dir():
        print(f"no such run root: {a.root}")
        return 2
    rows = collect(a.root, a.runs_dir)
    if not rows:
        print(f"no runs found under {a.root}/*/{a.runs_dir}/…")
        return 1
    text = render(rows)
    print(text)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
        print(f"\n[written to {a.out}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
