#!/usr/bin/env python3
"""Check the SWE-bench fixture setup BEFORE spending hours of agent time.

Two classes of failure cost the most when found late: a toolchain that cannot build
the repo at all (every run fails and reads as the agent's fault), and a fixture whose
tests do not actually fail (nothing to fix — the run grades meaningless). This checks
the environment, and optionally compiles one fixture and confirms the bug reproduces.

    python3 scripts/swe_doctor.py                     # environment only (fast)
    python3 scripts/swe_doctor.py --fixture swe-runs/fasterxml_jackson-core_pr1309
    python3 scripts/swe_doctor.py --all swe-runs      # compile-check every fixture
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

OK, WARN, BAD = "✓", "!", "✗"


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 900) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, "not found"
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"


def check_env() -> list[tuple[str, str, str]]:
    """[(status, name, detail)] — everything a fixture run needs on the host."""
    out = []
    for tool, args in (("git", ["--version"]), ("java", ["-version"]),
                       ("javac", ["-version"]), ("mvn", ["-v"])):
        if not shutil.which(tool):
            out.append((BAD if tool in ("git", "java") else WARN, tool, "not on PATH"))
            continue
        _, txt = _run([tool, *args], timeout=60)
        first = next((ln for ln in txt.splitlines() if ln.strip()), "")
        out.append((OK, tool, first.strip()[:70]))

    # Gradle projects ship ./gradlew, so a system gradle is optional.
    out.append((OK if shutil.which("gradle") else WARN, "gradle",
                "on PATH" if shutil.which("gradle") else
                "absent (fine — Gradle repos use their own ./gradlew)"))

    java_home = os.environ.get("JAVA_HOME")
    out.append((OK if java_home else WARN, "JAVA_HOME",
                java_home or "unset (Maven usually still works; set it if builds fail)"))

    key = os.environ.get("DEEPSEEK_API_KEY")
    out.append((OK if key else BAD, "DEEPSEEK_API_KEY",
                f"set ({len(key)} chars)" if key else "unset — the agent cannot run"))

    try:
        import abench  # noqa: F401
        out.append((OK, "abench", "importable"))
    except Exception as exc:
        out.append((BAD, "abench", f"not importable: {exc}"))
    out.append((OK if shutil.which("abench") else BAD, "abench CLI",
                "on PATH" if shutil.which("abench") else "not on PATH (pip install -e .)"))
    return out


_VERIFY_RE = re.compile(r'command:\s*"([^"]+)"')


def _verify_cmd(fixture: Path) -> str | None:
    y = fixture / "experiment.yaml"
    if not y.is_file():
        return None
    m = _VERIFY_RE.search(y.read_text(encoding="utf-8", errors="replace"))
    return m.group(1) if m else None


def check_fixture(fixture: Path, compile_only: bool, timeout: int) -> list[str]:
    """Compile the buggy tree, and (unless compile_only) confirm the bug REPRODUCES:
    tests must FAIL in checkout/. A fixture whose tests already pass has nothing for
    the agent to fix and would silently score as a free win."""
    notes = []
    co, ref = fixture / "checkout", fixture / "reference"
    if not co.is_dir() or not ref.is_dir():
        return [f"{BAD} {fixture.name}: missing checkout/ or reference/"]

    cmd = _verify_cmd(fixture)
    if not cmd:
        return [f"{BAD} {fixture.name}: no verify command in experiment.yaml"]
    gradle = cmd.startswith("./gradlew")
    build = (["./gradlew", "compileTestJava", "--console=plain"] if gradle
             else ["mvn", "-B", "-q", "test-compile"])
    rc, txt = _run(build, cwd=co, timeout=timeout)
    if rc != 0:
        tail = "\n      ".join(txt.strip().splitlines()[-6:])
        return [f"{BAD} {fixture.name}: the BUGGY tree does not compile (rc={rc}).",
                f"      This is a toolchain/JDK problem, not the agent's:\n      {tail}"]
    notes.append(f"{OK} {fixture.name}: compiles")
    if compile_only:
        return notes

    rc, txt = _run(cmd.split(), cwd=co, timeout=timeout)
    if rc == 0:
        notes.append(f"{BAD} {fixture.name}: tests PASS in checkout/ — the bug does not "
                     "reproduce, so this instance grades nothing. Exclude it.")
    else:
        notes.append(f"{OK} {fixture.name}: tests fail in checkout/ (bug reproduces)")
    return notes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", type=Path, help="one fixture dir to check deeply")
    ap.add_argument("--all", type=Path, metavar="ROOT",
                    help="compile-check every fixture under ROOT (e.g. swe-runs)")
    ap.add_argument("--compile-only", action="store_true",
                    help="skip the (slow) test run that proves the bug reproduces")
    ap.add_argument("--timeout", type=int, default=1800)
    a = ap.parse_args()

    print("── environment ──")
    rows = check_env()
    for st, name, detail in rows:
        print(f" {st} {name:18} {detail}")
    blocking = [n for st, n, _ in rows if st == BAD]

    if a.fixture:
        print("\n── fixture ──")
        for line in check_fixture(a.fixture, a.compile_only, a.timeout):
            print(" " + line)
    elif a.all:
        fixtures = sorted(p for p in a.all.iterdir()
                          if p.is_dir() and (p / "experiment.yaml").is_file())
        print(f"\n── {len(fixtures)} fixture(s) under {a.all} ──")
        for f in fixtures:
            for line in check_fixture(f, True, a.timeout):   # compile only: keep it bearable
                print(" " + line)

    if blocking:
        print(f"\n{BAD} blocking: {', '.join(blocking)} — fix these before running the batch")
        return 1
    print(f"\n{OK} environment looks runnable"
          + ("" if (a.fixture or a.all) else
             "  (add --fixture <dir> to prove one fixture builds and the bug reproduces)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
