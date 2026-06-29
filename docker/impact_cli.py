#!/usr/bin/env python3
"""`impact` — a shell command for the sandbox.

Models instinctively run `bash impact` instead of invoking the opencode `impact`
tool, so the sandbox puts THIS on PATH as `impact`. Two modes:

  impact              Read your uncommitted diff → per changed method, the tests
                      that cover it, PLUS a ready-to-run, blast-radius-aware test
                      command: a focused subset while you iterate, and the FULL
                      suite when the change is broad (a focused subset would hide
                      failures) or before you declare done.

  impact failures     Read failing test names (piped from a test run, or passed
                      as args) → split them into "caused by a method you changed"
                      vs "not covered by your change" (pre-existing / unrelated).
                      e.g.  ./gradlew :test --continue 2>&1 | impact failures

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

_MAX_TESTS = 40    # cap the per-method test list in the output
_MAX_CLASSES = 8   # cap the test classes in the suggested gradle command
_MAX_SPECIFIC = 8  # cap the specific name-matched test methods in the suggestion

# Blast-radius thresholds: above EITHER, a focused subset can't be trusted (it
# would hide failures in the tests it omits), so we steer to the full suite.
_BROAD_TESTS = 40    # distinct tests covering the change
_BROAD_CLASSES = 10  # distinct test classes covering the change


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


def deleted_lines(diff_text: str) -> dict[str, set[int]]:
    """Map each file to the set of OLD-side (base) line numbers it deletes.

    Method attribution uses THIS, not the new side: the agent's base (git HEAD)
    is the seed/stub, and methods.json spans are anchored to that same seed — so
    overlapping the *deleted* lines against the spans is coordinate-consistent and
    immune to line drift (the new side grows unboundedly as a stubbed method is
    implemented; the deleted side stays pinned to the stub). For a pure-insertion
    hunk (no deletions) the base anchor line is included so the insertion is still
    attributed to its enclosing method."""
    out: dict[str, set[int]] = {}
    cur: str | None = None
    oldline = 0
    hunk_del = 0
    hunk_anchor: int | None = None

    def flush_anchor() -> None:
        nonlocal hunk_del, hunk_anchor
        if cur is not None and hunk_del == 0 and hunk_anchor is not None:
            out[cur].add(hunk_anchor)
        hunk_del = 0
        hunk_anchor = None

    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            flush_anchor(); cur = line[6:]; out.setdefault(cur, set())
        elif line.startswith("+++ "):
            flush_anchor(); cur = None
        elif line.startswith("@@"):
            flush_anchor()
            m = re.search(r"-(\d+)", line)
            oldline = int(m.group(1)) if m else 0
            hunk_anchor = oldline
        elif cur is not None and line.startswith("-"):
            out[cur].add(oldline); hunk_del += 1; oldline += 1
        elif cur is not None and not line.startswith("+") and not line.startswith("\\"):
            oldline += 1  # context line advances the old-side counter
    flush_anchor()
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


def _name_tokens(fqn: str) -> list[str]:
    """Lowercased simple-name tokens that flag the genuinely relevant tests: the
    changed method's own name and its innermost enclosing class
    ("a.B$C$Inner.method" → ["method", "inner"])."""
    cls, _, method = fqn.rpartition(".")
    inner = cls.replace("$", ".").rsplit(".", 1)[-1] if cls else ""
    return [t.lower() for t in (method, inner) if t]


def _name_matches(test: str, tokens: list[str]) -> bool:
    low = test.lower()
    return any(tok in low for tok in tokens)


def _command_block(matched_tests, classes, coverers_total, classes_total,
                   test_cmd, total_tests=None) -> list[str]:
    """Blast-radius-aware, two-tier command guidance.

    BROAD change (covers more than the thresholds): a focused subset would hide
    failures, so the full suite is the source of truth (optionally spot-check the
    closest tests while iterating). NARROW change: a focused subset for the inner
    loop, then the full suite as the done-gate. The command verb comes from the
    project's ``test_command`` so it is correct to paste (e.g. ``:test`` for a
    Gradle module, ``mvn test`` for Maven)."""
    full = f"  {test_cmd} --continue"
    scope = (f"{coverers_total} tests across {classes_total} test classes"
             + (f" (of {total_tests} in the suite)" if total_tests else ""))
    if coverers_total > _BROAD_TESTS or classes_total > _BROAD_CLASSES:
        out = [f"Your change is BROAD — covered by {scope}. A focused subset would "
               f"MISS failures in the tests it omits, so the FULL suite is the "
               f"source of truth here — run it, and don't trust a green subset:",
               full]
        spot = matched_tests[:_MAX_SPECIFIC]
        if spot:
            cmd = " ".join(f"--tests '{t}'" for t in spot)
            out += ["(While iterating you may spot-check the closest tests first:",
                    f"  {test_cmd} {cmd}",
                    " — but run the full suite before you finish.)"]
        return out
    out: list[str] = []
    if matched_tests:
        cmd = " ".join(f"--tests '{t}'" for t in matched_tests[:_MAX_SPECIFIC])
        out += ["Focused run — tests whose name targets the change "
                "(run these while iterating):",
                f"  {test_cmd} {cmd}"]
    elif classes:
        top = sorted(classes, key=lambda c: -classes[c])[:_MAX_CLASSES]
        cmd = " ".join(f"--tests '{c}'" for c in top)
        out += ["Focused run of the affected test classes (while iterating):",
                f"  {test_cmd} {cmd}"]
    out += ["Before you finish, confirm nothing else broke with the full suite:",
            full]
    return out


def build_report(changes, methods, coverage, mutation, total_tests=None,
                 test_cmd="./gradlew test") -> str:
    changed = methods_for(changes, methods)
    if not changed:
        return ("# impact\n\nNo changed methods matched the impact data "
                "(edit a tracked method, or there's no coverage for it).\n")
    lines = ["# impact — tests affected by your uncommitted changes", ""]
    classes: dict[str, int] = {}
    matched_tests: list[str] = []     # name-matched coverers across all changed methods
    all_coverers: set[str] = set()    # every distinct coverer — for the blast radius
    all_classes: set[str] = set()
    for fqn in changed:
        covers = list(coverage.get(fqn, []))
        all_coverers.update(covers)
        all_classes.update(_test_class(t) for t in covers)
        blind = list(mutation.get(fqn, [])) if isinstance(mutation, dict) else []
        # The coverage list is Tier-2 — ANY test that executes the method — so for
        # a broadly-covered method the truly relevant tests are buried. Float the
        # ones whose name echoes the method/innermost class to the top; that is
        # what a capable agent ends up grepping for by hand.
        tokens = _name_tokens(fqn)
        named = [t for t in covers if _name_matches(t, tokens)]
        ordered = named + [t for t in covers if t not in named]
        for t in named:
            if t not in matched_tests:
                matched_tests.append(t)
        lines.append(f"## {fqn}  (changed)")
        if covers:
            hint = " — name-matched first" if named else ""
            lines.append(f"{len(covers)} tests cover this method "
                         f"(Tier-2 coverers{hint}; run these to verify):")
            for t in ordered[:_MAX_TESTS]:
                tag = "   <- name match" if t in named else ""
                lines.append(f"  - {t}{tag}")
                classes[_test_class(t)] = classes.get(_test_class(t), 0) + 1
            if len(ordered) > _MAX_TESTS:
                lines.append(f"  + {len(ordered) - _MAX_TESTS} more")
        else:
            lines.append("(no coverage data for this method)")
        if blind:
            lines.append(f"BLIND SPOTS (changed lines no test detects): {blind}")
        lines.append("")
    lines += _command_block(matched_tests, classes, len(all_coverers),
                            len(all_classes), test_cmd, total_tests)
    lines.append("")
    if not mutation:
        lines.append("Note: mutation data is empty → Tier-1 (cover+kill) and "
                     "blind-spots are unavailable; the lists above are "
                     "coverage-based (Tier-2).")
    return "\n".join(lines) + "\n"


# ── Failure attribution (impact failures) ─────────────────────────────────────

def _norm_key(name: str) -> str | None:
    """Normalize a test identifier to ``simpleclass.method`` (lowercased) so a
    gradle line ("AbbreviationMatcherTest > testX"), a fully-qualified name
    ("picocli.AbbreviationMatcherTest.testX") and a bare "Class.method" all
    compare equal. Returns None when the string isn't a test identifier."""
    s = name.strip()
    if not s:
        return None
    if ">" in s:                                   # gradle: "[pkg.]Class > method[(...)]"
        cls, _, method = s.partition(">")
        cls = cls.strip().split(".")[-1]
        method = re.split(r"[(\s]", method.strip())[0]
    elif "." in s:                                 # FQN or Class.method
        cls_full, _, method = s.rpartition(".")
        cls = cls_full.split(".")[-1]
        method = re.split(r"[(\s]", method.strip())[0]
    else:
        return None
    if not cls or not method:
        return None
    return f"{cls}.{method}".lower()


def _extract_failed(text: str) -> list[str]:
    """Pull failing test names out of raw test-runner output: a line ending in
    FAILED yields the identifier before it — but only if it parses as a test
    name, so gradle TASK failures ('> Task :test FAILED', 'BUILD FAILED') are
    skipped."""
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line.endswith("FAILED"):
            name = line[: -len("FAILED")].strip()
            if name and _norm_key(name) is not None:
                out.append(name)
    return out


def _gather_failed(args: list[str], stdin_text: str) -> list[str]:
    """Collect failing test names from explicit args or piped output. Args win;
    otherwise parse FAILED lines from stdin, falling back to one-name-per-line."""
    if args:
        names = list(args)
    elif stdin_text:
        names = _extract_failed(stdin_text)
        if not names:  # not runner output — assume a plain list, one per line
            names = [ln.strip() for ln in stdin_text.splitlines() if ln.strip()]
    else:
        names = []
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def attribute_failures(failed, changes, methods, coverage):
    """Split ``failed`` test names into those covered by a method the agent
    changed (likely caused by the edit) and those that are not. Returns
    ``(changed_methods, explained, unexplained)`` where ``explained`` is a list
    of ``(failed_name, [covering methods])``."""
    changed = methods_for(changes, methods)
    cover_index: dict[str, set[str]] = {}
    for fqn in changed:
        for t in coverage.get(fqn, []):
            k = _norm_key(t)
            if k:
                cover_index.setdefault(k, set()).add(fqn)
    explained: list[tuple[str, list[str]]] = []
    unexplained: list[str] = []
    for name in failed:
        k = _norm_key(name)
        hit = cover_index.get(k) if k else None
        if hit:
            explained.append((name, sorted(hit)))
        else:
            unexplained.append(name)
    return changed, explained, unexplained


def build_failures_report(failed, changes, methods, coverage) -> str:
    if not failed:
        return ("# impact — failure attribution\n\nNo failing tests given. Pipe a "
                "test run's output (`./gradlew :test --continue 2>&1 | impact "
                "failures`) or pass names as arguments.\n")
    changed, explained, unexplained = attribute_failures(failed, changes, methods, coverage)
    lines = [f"# impact — failure attribution ({len(failed)} failing test(s))", ""]
    if not changed:
        lines += ["No changed methods matched the impact data, so these failures "
                  "can't be tied to your edit — did you edit a tracked method yet?",
                  ""]
    lines.append(f"Caused by a method you changed ({len(explained)} — fix these first):")
    if explained:
        for name, ms in explained[:_MAX_TESTS]:
            lines.append(f"  - {name}   (covers {', '.join(ms)})")
        if len(explained) > _MAX_TESTS:
            lines.append(f"  + {len(explained) - _MAX_TESTS} more")
    else:
        lines.append("  (none of the failing tests cover a method you changed)")
    lines.append("")
    lines.append(f"NOT covered by your change ({len(unexplained)} — likely "
                 f"pre-existing, unrelated, or flaky):")
    if unexplained:
        for name in unexplained[:_MAX_TESTS]:
            lines.append(f"  - {name}")
        if len(unexplained) > _MAX_TESTS:
            lines.append(f"  + {len(unexplained) - _MAX_TESTS} more")
    else:
        lines.append("  (every failure traces back to a method you changed)")
    lines += ["",
              "Coverage is Tier-2 (any test that executes the method) and may be "
              "incomplete, so treat 'NOT covered' as a strong hint, not proof."]
    return "\n".join(lines) + "\n"


# ── Config loading + dispatch ─────────────────────────────────────────────────

def _load(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _find_config(cwd: Path) -> Path | None:
    for d in [cwd, *cwd.parents]:
        c = d / ".opencode" / "impact.json"
        if c.is_file():
            return c
    return None


def _git_diff(repo_root: Path) -> str:
    try:
        return subprocess.run(["git", "diff", "HEAD"], cwd=repo_root,
                              capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    mode = "report"
    if argv and argv[0] == "failures":
        mode, argv = "failures", argv[1:]

    config = _find_config(Path.cwd())
    if config is None:
        print("impact: no .opencode/impact.json found — nothing to analyze.")
        return 0
    cfg = _load(config)
    base = config.parent
    methods = _load(base / cfg.get("methods", "../.impact/methods.json"))
    coverage = _load(base / cfg.get("coverage", "../.impact/coverage.json"))
    mutation = _load(base / cfg.get("mutation", "../.impact/mutation.json"))
    test_cmd = cfg.get("test_command", "./gradlew test")
    total_tests = cfg.get("total_tests")
    diff = _git_diff(config.parent.parent)
    # Attribute by DELETED (base-side) lines: the base is the seed/stub that
    # methods.json spans are anchored to, so this is drift-immune (see
    # deleted_lines). Using the new side mis-attributes a reconstructed stub to
    # whatever methods followed it in the seed (the picocli putValue bug).
    changes = deleted_lines(diff)

    if mode == "failures":
        stdin_text = ""
        try:
            if not sys.stdin.isatty():
                stdin_text = sys.stdin.read()
        except (OSError, ValueError):
            stdin_text = ""
        failed = _gather_failed(argv, stdin_text)
        print(build_failures_report(failed, changes, methods, coverage))
        return 0

    if not diff.strip():
        print("impact: no uncommitted changes yet — edit the method first, "
              "then run `impact` to see which tests to run.")
        return 0
    print(build_report(changes, methods, coverage, mutation, total_tests, test_cmd))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as exc:  # never break the agent's shell
        print(f"impact: unexpected error ({exc!r})")
        sys.exit(0)
