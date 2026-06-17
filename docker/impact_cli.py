#!/usr/bin/env python3
"""`impact` — a shell command for the sandbox.

Models instinctively run `bash impact` instead of invoking the opencode `impact`
tool, so the sandbox puts THIS on PATH as `impact`. With no arguments it reads
the run's `.opencode/impact.json` config + the agent's uncommitted git diff and
prints, per changed method, the tests that cover it (so the agent can run a
focused subset instead of the whole suite).

Self-contained (stdlib only) so it runs inside the sandbox image, which has no
abench/GT Python on its path. It approximates the GT opencode tool from the same
precomputed `.impact/*.json` data; it is NOT a reimplementation of GT internals.
Never crashes the caller's shell: any failure prints a short note and exits 0.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

_MAX_TESTS = 40   # cap the per-method test list in the output
_MAX_CLASSES = 8  # cap the test classes in the suggested gradle command


def changed_lines(diff_text: str) -> dict[str, set[int]]:
    """Map each file in a unified diff to the set of NEW-side line numbers it
    adds/changes (the lines the agent wrote)."""
    out: dict[str, set[int]] = {}
    cur: str | None = None
    newline = 0
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            cur = line[6:]
            out.setdefault(cur, set())
        elif line.startswith("+++ "):
            cur = None
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            newline = int(m.group(1)) if m else 0
        elif cur is not None and line.startswith("+"):
            out[cur].add(newline)
            newline += 1
        elif cur is not None and not line.startswith("-") and not line.startswith("\\"):
            newline += 1  # context line advances the new-side counter
    return {f: ls for f, ls in out.items() if ls}


def _path_match(changed: str, method_file: str) -> bool:
    changed = changed.lstrip("./")
    method_file = method_file.lstrip("./")
    return (changed == method_file
            or changed.endswith("/" + method_file)
            or method_file.endswith("/" + changed))


def methods_for(changes: dict[str, set[int]], methods: dict) -> list[str]:
    """Methods whose [start,end] span overlaps a changed line in a matching file."""
    hits: list[str] = []
    for fqn, loc in methods.items():
        f, s, e = loc.get("file"), loc.get("start"), loc.get("end")
        if not f or s is None or e is None:
            continue
        for path, lines in changes.items():
            if _path_match(path, f) and any(s <= ln <= e for ln in lines):
                hits.append(fqn)
                break
    return sorted(set(hits))


def _test_class(test: str) -> str:
    # "pkg.HelpTest.testX" → "pkg.HelpTest" (drop the trailing method name)
    return test.rsplit(".", 1)[0] if "." in test else test


def build_report(changes, methods, coverage, mutation) -> str:
    changed = methods_for(changes, methods)
    if not changed:
        return ("# impact\n\nNo changed methods matched the impact data "
                "(edit a tracked method, or there's no coverage for it).\n")
    lines = ["# impact — tests affected by your uncommitted changes", ""]
    classes: dict[str, int] = {}
    for fqn in changed:
        covers = list(coverage.get(fqn, []))
        blind = list(mutation.get(fqn, [])) if isinstance(mutation, dict) else []
        lines.append(f"## {fqn}  (changed)")
        if covers:
            lines.append(f"{len(covers)} tests cover this method "
                         "(Tier-2 coverers — run these to verify):")
            for t in covers[:_MAX_TESTS]:
                lines.append(f"  - {t}")
                classes[_test_class(t)] = classes.get(_test_class(t), 0) + 1
            if len(covers) > _MAX_TESTS:
                lines.append(f"  + {len(covers) - _MAX_TESTS} more")
        else:
            lines.append("(no coverage data for this method)")
        if blind:
            lines.append(f"BLIND SPOTS (changed lines no test detects): {blind}")
        lines.append("")
    if classes:
        top = sorted(classes, key=lambda c: -classes[c])[:_MAX_CLASSES]
        cmd = " ".join(f"--tests '{c}'" for c in top)
        lines += ["Focused run of the affected test classes:",
                  f"  ./gradlew test {cmd}", ""]
    if not mutation:
        lines.append("Note: mutation data is empty → Tier-1 (cover+kill) and "
                     "blind-spots are unavailable; the lists above are "
                     "coverage-based (Tier-2).")
    return "\n".join(lines) + "\n"


def _load(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def main(argv=None) -> int:
    cwd = Path.cwd()
    config = None
    for d in [cwd, *cwd.parents]:
        c = d / ".opencode" / "impact.json"
        if c.is_file():
            config = c
            break
    if config is None:
        print("impact: no .opencode/impact.json found — nothing to analyze.")
        return 0
    cfg = _load(config)
    base = config.parent
    methods = _load((base / cfg.get("methods", "../.impact/methods.json")))
    coverage = _load((base / cfg.get("coverage", "../.impact/coverage.json")))
    mutation = _load((base / cfg.get("mutation", "../.impact/mutation.json")))
    try:
        diff = subprocess.run(["git", "diff", "HEAD"], cwd=config.parent.parent,
                              capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        diff = ""
    if not diff.strip():
        print("impact: no uncommitted changes yet — edit the method first, "
              "then run `impact` to see which tests to run.")
        return 0
    print(build_report(changed_lines(diff), methods, coverage, mutation))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as exc:  # never break the agent's shell
        print(f"impact: unexpected error ({exc!r})")
        sys.exit(0)
