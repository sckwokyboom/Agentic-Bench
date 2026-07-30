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
        rc, txt = _run([tool, *args], timeout=60)
        first = next((ln for ln in txt.splitlines() if ln.strip()), "")
        # Present-but-broken is not OK: a mvn that cannot start (bad JAVA_HOME) would
        # otherwise be reported as a healthy version line that is really an error.
        out.append((OK if rc == 0 else BAD, tool,
                    first.strip()[:70] + ("" if rc == 0 else f"  [exit {rc} — broken]")))

    # Gradle projects ship ./gradlew, so a system gradle is optional.
    out.append((OK if shutil.which("gradle") else WARN, "gradle",
                "on PATH" if shutil.which("gradle") else
                "absent (fine — Gradle repos use their own ./gradlew)"))

    # A JAVA_HOME pointing at a different JDK than the java on PATH makes Maven and
    # javac disagree — the build then fails for reasons no source change can fix.
    java_home = os.environ.get("JAVA_HOME")
    if not java_home:
        out.append((WARN, "JAVA_HOME", "unset (Maven usually still works; set it if builds fail)"))
    else:
        _, ver = _run(["java", "-version"], timeout=60)
        on_path = re.search(r'"(\d+)[.\"]', ver)
        in_home = re.search(r"(?:java-|jdk-?)(\d+)", java_home)
        if on_path and in_home and on_path.group(1) != in_home.group(1):
            out.append((WARN, "JAVA_HOME",
                        f"{java_home} looks like JDK {in_home.group(1)} but `java` on "
                        f"PATH is {on_path.group(1)} — Maven uses JAVA_HOME, so builds "
                        "may fail in ways the agent cannot fix"))
        else:
            out.append((OK, "JAVA_HOME", java_home))

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

#: Maven/Gradle print the CAUSE first and then a wall of generic help; the tail is
#: exactly the useless part. Keep the lines that name a real problem.
_NOISE = ("To see the full stack trace", "Re-run Maven", "For more information",
          "[Help 1]", "[Help 2]", "http://cwiki.apache.org", "BUILD FAILURE",
          "----------", "Try:", "Run with --stacktrace", "* Get more help",
          "Deprecated Gradle features", "BUILD FAILED in")


def _build_error(txt: str) -> list[str]:
    """The lines that actually say what went wrong (first, not last)."""
    keep = [ln.rstrip() for ln in txt.splitlines()
            if ln.strip() and any(k in ln for k in ("[ERROR]", "error:", "FAILURE",
                                                    "Caused by", "Could not", "Cannot"))
            and not any(n in ln for n in _NOISE)]
    return keep[:8] or [ln.rstrip() for ln in txt.strip().splitlines()[-6:]]


def _tests_need_the_fix(txt: str) -> bool:
    """True when the compile errors are TEST files missing symbols the fix adds.

    A whole class of SWE-bench instances is 'add this API': the fix introduces new
    methods and the new tests call them, so base+test_patch cannot compile. That is
    a property of the instance, not of the host, and no JDK or repository setting
    changes it — so it must not be reported as a toolchain problem.
    """
    hits = [ln for ln in txt.splitlines()
            if ("cannot find symbol" in ln
                or "does not override or implement a method" in ln)]
    return bool(hits) and all(("/src/test/" in ln or "/src/it/" in ln
                               or "Test.java" in ln or "Tests.java" in ln)
                              for ln in hits if "/" in ln)


def _build_hints(txt: str) -> list[str]:
    """Named remedies for the failure modes these old Java repos actually hit."""
    hints = []
    if "maven-default-http-blocker" in txt or "blocked mirror" in txt:
        hints.append("Maven 3.8+ blocks plain-HTTP repositories, and these old poms "
                     "still reference them. Add an https mirror to ~/.m2/settings.xml, "
                     "or use Maven 3.6.x for these fixtures.")
    if "UnresolvableModelException" in txt or "Non-resolvable parent POM" in txt:
        hints.append("Maven cannot fetch the PARENT pom — usually no route to Maven "
                     "Central (proxy/offline) or the http-blocker above. Test with: "
                     "mvn -B -q dependency:resolve  in the checkout.")
    if "invalid target release" in txt or "release version" in txt:
        hints.append("JDK too new/old for this project's source level — point JAVA_HOME "
                     "at the JDK the project expects (jackson-core builds under 8/11).")
    if "JAVA_HOME" in txt:
        hints.append("JAVA_HOME is referenced in the error — check it matches the java "
                     "on PATH (a mismatch makes Maven and javac disagree).")
    return hints


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
        if _tests_need_the_fix(txt):
            # Not a toolchain fault and not fixable by configuration: the instance's
            # fix ADDS API that its new tests call, so base+test_patch cannot compile
            # until the fix exists. Unusable as a fixture — the agent would have to
            # invent the exact signature before any test could even run.
            return [f"{BAD} {fixture.name}: UNUSABLE INSTANCE — the new tests call API "
                    "that only the fix introduces, so the buggy tree cannot compile.",
                    *(f"      {ln}" for ln in _build_error(txt)[:4]),
                    "      Exclude it:  python3 scripts/swe_doctor.py --all <root> --prune"]
        return [f"{BAD} {fixture.name}: the BUGGY tree does not compile (rc={rc}). "
                "This is a toolchain problem, not the agent's:",
                *(f"      {ln}" for ln in _build_error(txt)),
                *(f"      HINT: {h}" for h in _build_hints(txt))]
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
    ap.add_argument("--prune", action="store_true",
                    help="with --all: mark fixtures that do not compile as excluded "
                         "(experiment.yaml -> .excluded) so the batch skips them")
    ap.add_argument("--timeout", type=int, default=1800)
    a = ap.parse_args()

    print("── environment ──")
    rows = check_env()
    for st, name, detail in rows:
        print(f" {st} {name:18} {detail}")
    blocking = [n for st, n, _ in rows if st == BAD]

    bad_fixtures = 0
    if a.fixture:
        print("\n── fixture ──")
        lines = check_fixture(a.fixture, a.compile_only, a.timeout)
        bad_fixtures += any(ln.startswith(BAD) for ln in lines)
        for line in lines:
            print(" " + line)
    elif a.all:
        fixtures = sorted(p for p in a.all.iterdir()
                          if p.is_dir() and (p / "experiment.yaml").is_file())
        print(f"\n── {len(fixtures)} fixture(s) under {a.all} ──")
        pruned = []
        for f in fixtures:
            lines = check_fixture(f, True, a.timeout)   # compile only: keep it bearable
            failed = any(ln.startswith(BAD) for ln in lines)
            bad_fixtures += failed
            for line in lines:
                print(" " + line)
            if failed and a.prune:
                # A sticky marker: renaming the yaml alone is undone by the next
                # `build`, which would regenerate it and silently re-include the
                # fixture. The generator honours EXCLUDED.
                (f / "EXCLUDED").write_text(
                    "excluded by swe_doctor --prune: the buggy tree does not compile\n")
                y = f / "experiment.yaml"
                if y.is_file():
                    y.rename(f / "experiment.yaml.excluded")
                pruned.append(f.name)
        if pruned:
            # Regenerating the run script is the caller's job (swe.sh build); the
            # generated script skips a fixture whose experiment.yaml is absent.
            print(f"\n excluded {len(pruned)}: {', '.join(pruned)}")
            print(" re-run  ./scripts/swe.sh build  to refresh the run script, then run.")
            bad_fixtures = 0

    # A green env summary printed under a screen of failing fixtures is worse than
    # useless — the batch would burn hours producing nothing but build errors.
    if blocking or bad_fixtures:
        print("")
        if blocking:
            print(f"{BAD} blocking: {', '.join(blocking)}")
        if bad_fixtures:
            print(f"{BAD} {bad_fixtures} fixture(s) do not build — running the batch now "
                  "would only produce build failures, not agent results.")
        print("Fix the above before running the batch.")
        return 1
    print(f"\n{OK} environment looks runnable"
          + ("" if (a.fixture or a.all) else
             "  (add --fixture <dir> to prove one fixture builds and the bug reproduces)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
