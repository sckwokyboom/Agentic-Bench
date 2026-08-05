#!/usr/bin/env python3
"""Rank picocli methods as A/B targets by MEASURING what removing them breaks.

Picking targets by intuition is how you end up measuring nothing. A method whose
removal breaks two tests gives the causal loop nothing to rank; one that breaks the
entire suite gives it no signal either, because every path looks equally guilty. What
makes a target useful is measurable, so this measures it: strip the body, compile, run
the suite, count the damage.

Per candidate it reports:
  failures   how many tests the stub breaks — the size of the symptom
  classes    how many distinct test CLASSES fail. THIS is the causal-loop axis: a
             failure spread over many classes means the symptom is far from the cause
             and ranking candidate paths is a real problem to solve. One class means
             the test that fails already names the method.
  body       lines removed — how much has to be re-derived, i.e. whether a single
             lucky guess can pass
  compiles   a stub that does not compile is not a task, it is a broken fixture

Nothing here touches experiments/picocli-putValue/original: the tree is copied once
and every strip happens in the copy, because a contaminated reference silently poisons
target_similarity (it happened once already).

    python3 scripts/picocli_candidates.py                 # the known-coverage set
    python3 scripts/picocli_candidates.py --methods putValue,toString --out cand.md
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXP = REPO / "experiments" / "picocli-putValue"
ORIGINAL = EXP / "original"
ARTIFACTS = EXP / "overlays" / "impact-artifacts" / ".impact"
SRC_REL = "src/main/java/picocli/CommandLine.java"

sys.path.insert(0, str(REPO / "scripts"))
from picocli_sweep import body_span, strip_body, STUB_MARK  # noqa: E402

#: "2437 tests completed, 432 failed, 1 skipped"
_COUNTS = re.compile(r"(\d+)\s+tests?\s+completed(?:,\s*(\d+)\s+failed)?")


def candidates(cov: dict, meths: dict, want: list[str] | None) -> list[tuple[str, str]]:
    """Resolve names to FQNs across the WHOLE file, not just the covered region.

    Restricting candidates to coverage.json confined every scan to TextTable, and
    measuring that region showed why it is the wrong place to look: stripping any
    method there breaks the same ~40 classes, because help rendering is on nearly
    every test's path. The interesting targets — the parser, arity, ANSI text — are
    elsewhere in the same file and have no coverage entry, so resolution now falls
    back to the project-wide method index. Accepts `method` or `Class.method`; a
    bare name that matches several classes is reported rather than guessed.
    """
    in_file = {fqn: loc for fqn, loc in meths.items()
               if SRC_REL in str(loc.get("file", ""))}
    by_short: dict[str, list[str]] = {}
    for fqn in in_file:
        by_short.setdefault(fqn.rsplit(".", 1)[-1], []).append(fqn)
        cls = fqn.rsplit(".", 1)[0].split("$")[-1]
        by_short.setdefault(f"{cls}.{fqn.rsplit('.', 1)[-1]}", []).append(fqn)
    names = want or sorted(k.rsplit(".", 1)[-1] for k in cov)
    out: list[tuple[str, str]] = []
    for n in names:
        hits = by_short.get(n) or []
        if not hits:
            print(f"  ? {n}: no such method in {SRC_REL}")
        elif len(hits) > 1 and "." not in n:
            classes = sorted({h.rsplit(".", 1)[0].split("$")[-1] for h in hits})
            print(f"  ? {n}: ambiguous across {classes} — qualify it as Class.{n}")
        else:
            out.append((n, hits[0]))
    return out


def failing_classes(tree: Path) -> tuple[int, int, int]:
    """(failures, failing test classes, TOTAL test classes) from the JUnit XML."""
    results = tree / "build" / "test-results" / "test"
    failures, classes, total = 0, set(), 0
    for xml in results.glob("*.xml"):
        total += 1
        try:
            text = xml.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        n = len(re.findall(r"<(failure|error)\b", text))
        if n:
            failures += n
            m = re.search(r'<testsuite[^>]*\bname="([^"]+)"', text)
            classes.add(m.group(1) if m else xml.stem)
    return failures, len(classes), total


def measure(tree: Path, name: str, decl_line: int, timeout: int) -> dict:
    src = tree / SRC_REL
    pristine = src.read_text(encoding="utf-8")
    try:
        removed = strip_body(src, decl_line)
        assert STUB_MARK in src.read_text(encoding="utf-8")
        t0 = time.monotonic()
        p = subprocess.run(
            ["./gradlew", ":test", "--continue", "--rerun-tasks", "--console=plain"],
            cwd=tree, capture_output=True, text=True, errors="replace", timeout=timeout)
        dt = time.monotonic() - t0
        blob = (p.stdout or "") + (p.stderr or "")
        compiles = "COMPILATION ERROR" not in blob and "error: " not in blob
        failures, classes, total = failing_classes(tree)
        if not failures:                       # fall back to gradle's own tally
            m = _COUNTS.search(blob)
            failures = int(m.group(2) or 0) if m else 0
        return {"method": name, "body": removed, "failures": failures,
                "classes": classes, "total_classes": total,
                "share": (classes / total) if total else 0.0,
                "compiles": compiles, "secs": round(dt)}
    finally:
        src.write_text(pristine, encoding="utf-8")   # never leave a stubbed tree


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--methods", help="comma-separated (default: every covered method)")
    ap.add_argument("--work", type=Path, default=REPO / ".picocli-scan",
                    help="scratch copy of the tree (original/ is never modified)")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--keep", action="store_true", help="keep the scratch tree")
    a = ap.parse_args()

    if not ORIGINAL.is_dir():
        print(f"missing {ORIGINAL} — run experiments/picocli-putValue/prepare.py first")
        return 2
    ref = (ORIGINAL / SRC_REL).read_text(encoding="utf-8")
    if STUB_MARK in ref:
        print(f"CONTAMINATED reference: {ORIGINAL / SRC_REL} already holds a stub.\n"
              "  Restore it first: python3 experiments/picocli-putValue/prepare.py "
              "--only fixtures --force")
        return 2

    cov = json.loads((ARTIFACTS / "coverage.json").read_text(encoding="utf-8"))
    meths = json.loads((ARTIFACTS / "methods.json").read_text(encoding="utf-8"))
    want = [m.strip() for m in a.methods.split(",")] if a.methods else None
    todo = candidates(cov, meths, want)
    if not todo:
        print("no candidates resolved")
        return 2

    if not a.work.is_dir():
        print(f"copying the tree to {a.work} (once) …")
        shutil.copytree(ORIGINAL, a.work, symlinks=True)

    rows = []
    for i, (name, fqn) in enumerate(todo, 1):
        lines = (a.work / SRC_REL).read_text(encoding="utf-8").splitlines(keepends=True)
        try:
            first, _ = body_span(lines, meths[fqn]["start"])
        except ValueError as exc:
            print(f"  [{i}/{len(todo)}] {name}: skipped ({exc})")
            continue
        print(f"  [{i}/{len(todo)}] {name}: stripping and running the suite …", flush=True)
        try:
            r = measure(a.work, name, meths[fqn]["start"], a.timeout)
        except subprocess.TimeoutExpired:
            print(f"      timed out after {a.timeout}s")
            continue
        r["tests_covering"] = len(cov.get(fqn, []))
        rows.append(r)
        print(f"      {r['failures']} failing test(s) across {r['classes']} class(es), "
              f"{r['body']} body lines, {r['secs']}s"
              + ("" if r["compiles"] else "  [DOES NOT COMPILE]"))

    # SATURATION is the thing to avoid, and the first scan proved it: in TextTable every
    # method — 4 lines or 46 — broke the same ~40 classes, and CaseAwareLinkedMap.get
    # breaks 89 of 73 source classes. When nearly the whole suite fails, the failures
    # cannot discriminate between candidate causes, so the causal loop has no signal to
    # rank on. Maximising breadth was exactly the wrong objective.
    #
    # A good target has a SUBSTANTIAL body (cannot be guessed in one shot) and a
    # LOCALISED failure (the failing set actually points somewhere).
    SATURATED = 0.60
    rows.sort(key=lambda r: (not r["compiles"], r["share"] >= SATURATED, -r["body"]))
    o = ["# picocli A/B candidates — measured", "",
         "| method | body lines | failing tests | classes | % of suite | compiles | verdict |",
         "|---|---|---|---|---|---|---|"]
    for r in rows:
        if not r["compiles"]:
            v = "broken fixture"
        elif not r["failures"]:
            v = "stub passes — nothing to fix"
        elif r["share"] >= SATURATED:
            v = "saturated — failures cannot discriminate"
        else:
            v = "**usable**"
        o.append(f"| {r['method']} | {r['body']} | {r['failures']} | {r['classes']} | "
                 f"{r['share']:.0%} | {'yes' if r['compiles'] else 'NO'} | {v} |")
    o += ["",
          f"**Saturation is the disqualifier.** Above ~{SATURATED:.0%} of the suite the "
          "failures stop discriminating: every candidate cause looks equally guilty, so "
          "there is nothing for a causal loop to rank. Measured proof — in TextTable a "
          "4-line reindent and a 46-line putValue both break the same ~40 classes, and "
          "CaseAwareLinkedMap.get breaks more classes than the project has test files.",
          "",
          "Among the rest, ranking is by BODY SIZE: the more lines the agent must "
          "re-derive, the less a single lucky guess can pass, and the more room there is "
          "for a repair loop to matter at all.", ""]
    usable = [r for r in rows if r["compiles"] and r["failures"]
              and r["share"] < SATURATED]
    if usable:
        o += ["**Suggested set:** "
              + ", ".join(r["method"] for r in usable[:6])
              + " — build them with "
              + f"`python3 scripts/picocli_sweep.py --methods "
                f"{','.join(r['method'] for r in usable[:6])} --container`.", ""]
    text = "\n".join(o)
    print("\n" + text)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
        print(f"[written to {a.out}]")
    if not a.keep:
        shutil.rmtree(a.work, ignore_errors=True)
    # The reference must be exactly as we found it.
    assert (ORIGINAL / SRC_REL).read_text(encoding="utf-8") == ref, \
        "reference tree changed during the scan"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
