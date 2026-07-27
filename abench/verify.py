"""Post-run verification — runs the project's test suite and parses the result."""
from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time
import xml.etree.ElementTree as _ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

from .verify_parsers import (
    parse_gradle_output,
    parse_maven_surefire,
    parse_pytest_output,
)

Status = Literal["passed", "failed", "skipped", "error", "timeout"]


@dataclass
class VerifyResult:
    status: Status
    reason: str = "skipped"   # passed|tests_failed|build_failed|tool_not_found|no_tests|timeout|unparseable|skipped
    message: str = ""
    command: str | None = None
    duration_s: float | None = None
    passed_count: int | None = None
    failed_count: int | None = None
    failed_names: list[str] = field(default_factory=list)
    raw_output: str = ""      # FULL combined stdout+stderr


@dataclass
class DetectResult:
    command: str | None
    system: str | None
    ambiguous: bool = False
    candidates: list[str] = field(default_factory=list)


def _gradle_command(workdir: Path) -> str:
    return "./gradlew test" if (workdir / "gradlew").exists() else "gradle test"


def _maven_command(workdir: Path) -> str:
    return "./mvnw test" if (workdir / "mvnw").exists() else "mvn test"


def detect_verify(workdir: Path) -> DetectResult:
    """Detect build system(s). Both Gradle and Maven present (e.g. a Gradle project
    with a stray root pom.xml — picocli) → prefer Gradle, flag ambiguity."""
    workdir = Path(workdir)
    has_gradle = any((workdir / f).exists() for f in
                     ("build.gradle", "build.gradle.kts", "settings.gradle",
                      "settings.gradle.kts", "gradlew"))
    has_maven = (workdir / "pom.xml").exists() or (workdir / "mvnw").exists()
    has_pytest = (workdir / "pyproject.toml").exists() and (workdir / "tests").is_dir()
    candidates: list[str] = []
    if has_gradle:
        candidates.append("gradle")
    if has_maven:
        candidates.append("maven")
    if has_pytest:
        candidates.append("pytest")
    if has_gradle and has_maven:
        return DetectResult(_gradle_command(workdir), "gradle", True, candidates)
    if has_gradle:
        return DetectResult(_gradle_command(workdir), "gradle", False, candidates)
    if has_maven:
        return DetectResult(_maven_command(workdir), "maven", False, candidates)
    if has_pytest:
        return DetectResult("pytest", "pytest", False, candidates)
    return DetectResult(None, None, False, [])


def detect_command(workdir: Path) -> str | None:
    """Back-compat: the canonical command, or None."""
    return detect_verify(workdir).command


_PARSER_BY_PREFIX: dict[str, Callable[[str], tuple[int, int, list[str]]]] = {
    "mvn": parse_maven_surefire,
    "./mvnw": parse_maven_surefire,
    "gradle": parse_gradle_output,
    "./gradlew": parse_gradle_output,
    "pytest": parse_pytest_output,
}


# Shell token boundaries: whitespace + the separators that can sit between a
# prefix and the real command (`cd x && ./gradlew test`, pipes, subshells).
_SHELL_TOKENS = re.compile(r"[\s;|&()<>]+")


def _parser_for(command: str) -> Callable[[str], tuple[int, int, list[str]]] | None:
    """Pick a test-output parser for a shell command.

    Scans ALL tokens (not just the first) so common prefixes don't hide the
    build tool: ``cd repo && ./gradlew test``, ``JAVA_HOME=… ./gradlew test``,
    ``timeout 600 mvn test``, ``sudo``/``nice``, ``bash -lc "./gradlew test"``.
    Matches by exact prefix or by basename, so absolute/relative paths to a
    wrapper (``/tmp/app/gradlew``) are recognised too.
    """
    for raw in _SHELL_TOKENS.split(command):
        tok = raw.strip("'\"`")
        if not tok:
            continue
        parser = _PARSER_BY_PREFIX.get(tok)
        if parser is not None:
            return parser
        base = tok.rsplit("/", 1)[-1]
        parser = _PARSER_BY_PREFIX.get(base) or _PARSER_BY_PREFIX.get(f"./{base}")
        if parser is not None:
            return parser
    return None


def _results_glob(workdir: Path, system: str) -> list[Path]:
    workdir = Path(workdir)
    patterns: tuple[str, ...] = ()
    if system == "gradle":
        patterns = ("**/build/test-results/**/*.xml",)
    elif system == "maven":
        patterns = ("target/surefire-reports/*.xml",
                    "target/failsafe-reports/*.xml",
                    "**/target/surefire-reports/*.xml",
                    "**/target/failsafe-reports/*.xml")
    # Overlapping patterns (e.g. `**/` also matching zero dirs) can return the
    # same file twice; dedupe by resolved path so suites aren't double-counted.
    seen: set[Path] = set()
    out: list[Path] = []
    for pat in patterns:
        for p in sorted(workdir.glob(pat)):
            rp = p.resolve()
            if rp not in seen:
                seen.add(rp)
                out.append(p)
    return out


def _parse_results_xml(workdir: Path, system: str) -> tuple[int, int, list[str]] | None:
    """Sum JUnit XML test-results (always written even when the console output has
    no parseable summary — e.g. modern Gradle, or Maven -q). Returns
    (passed, failed, failed_names) or None if no result files exist."""
    files = _results_glob(workdir, system)
    if not files:
        return None
    tests = failures = errors = skipped = 0
    names: list[str] = []
    found = False
    for f in files:
        try:
            root = _ET.parse(f).getroot()
        except _ET.ParseError:
            continue
        suites = [root] if root.tag == "testsuite" else root.iter("testsuite")
        for ts in suites:
            found = True
            tests += int(ts.get("tests", 0) or 0)
            failures += int(ts.get("failures", 0) or 0)
            errors += int(ts.get("errors", 0) or 0)
            skipped += int(ts.get("skipped", 0) or 0)
            for tc in ts.iter("testcase"):
                if tc.find("failure") is not None or tc.find("error") is not None:
                    cls = tc.get("classname", ""); nm = tc.get("name", "")
                    names.append(f"{cls}.{nm}" if cls else nm)
    if not found:
        return None
    failed = failures + errors
    passed = max(0, tests - failed - skipped)
    return passed, failed, names[:20]


def _system_of(command: str) -> str | None:
    first = command.split()[0] if command.split() else ""
    if first in ("gradle", "./gradlew"):
        return "gradle"
    if first in ("mvn", "./mvnw"):
        return "maven"
    if first == "defects4j":
        return "defects4j"
    return None


def _system_for_command(command: str) -> str | None:
    """Like _system_of but scans ALL shell tokens, so a wrapped command
    (`cd repo && ./gradlew test`, `JAVA_HOME=… mvn test`) is still recognised."""
    for raw in _SHELL_TOKENS.split(command):
        base = raw.strip("'\"`").rsplit("/", 1)[-1]
        if base in ("gradle", "gradlew"):
            return "gradle"
        if base in ("mvn", "mvnw"):
            return "maven"
        if base == "defects4j":
            return "defects4j"
    return None


def augment_for_full_run(command: str | None) -> str | None:
    """Append the build tool's keep-going-after-a-failure flag so ONE failing
    module doesn't abort the rest of the suite — Gradle `--continue`, Maven
    `--fail-at-end`. Without it a failing run stops early, so its downstream
    modules' tests never run and both the failed count and the suite total come
    out lower than a passing run's (a single early failure can hide a whole
    later module). Idempotent; only touches recognised Gradle/Maven commands."""
    if not command:
        return command
    system = _system_for_command(command)
    if system == "gradle" and not re.search(r"(?:^|\s)--continue(?:\s|$)", command):
        return f"{command} --continue"
    if system == "maven" and not re.search(r"(?:^|\s)(?:--fail-at-end|-fae)(?:\s|$)", command):
        return f"{command} --fail-at-end"
    return command


# A grading verify (host/reverify) must run the FULL multi-module suite, even when
# a prior run (the orchestration controller's per-round suite, or the agent's own
# test invocations) left Gradle's tasks up-to-date — otherwise Gradle skips the
# cached modules and only a non-cacheable module re-runs, so the parsed count is a
# tiny subset (the phased "ran 68 of 2437" undercount). `--rerun-tasks` forces a
# full re-execution. NOT for the controller's per-round runs (they must stay
# incremental/fast); only for the authoritative grading verify.
def augment_for_authoritative_run(command: str | None) -> str | None:
    command = augment_for_full_run(command)  # keep-going flag first
    if not command:
        return command
    if _system_for_command(command) == "gradle" and not re.search(
            r"(?:^|\s)--rerun-tasks(?:\s|$)", command):
        return f"{command} --rerun-tasks"
    return command


# Below this fraction of the reference's expected suite size, a COMPILED run that
# parsed pass/fail counts almost certainly under-executed (Gradle skipped up-to-date
# modules), rather than genuinely failing: a real failure still runs the whole suite
# under --continue (executed ≈ expected), and a compile break yields status='error'.
# So a gross undercount is an invalid MEASUREMENT, not a failure.
UNDERCOUNT_RATIO = 0.5


def undercount_override(status, passed, failed, expected_total):
    """Return (status, reason, message) overriding a gross under-execution to
    'invalid', else None. Pure — safe to unit-test and to apply post-hoc."""
    if status not in ("passed", "failed"):
        return None
    if not expected_total or passed is None or failed is None:
        return None
    executed = passed + failed
    if executed < expected_total * UNDERCOUNT_RATIO:
        return ("invalid", "under_executed",
                f"verify under-executed: ran {executed} of ~{expected_total} expected "
                "tests (Gradle likely skipped up-to-date modules) — measurement "
                "invalid, not a real failure")
    return None


def _clear_results(workdir: Path, system: str) -> None:
    """Delete stale JUnit XML result dirs BEFORE running verify, so the XML
    fallback can only ever read results written by THIS invocation. Without
    this, an agent that ran the tests green mid-task and then broke compilation
    would leave a stale green report that the fallback would misread as passed."""
    workdir = Path(workdir)
    if system == "defects4j":
        # Defects4J writes its verdict to these files at the checkout root; drop
        # any stale copy so we grade only THIS run.
        for name in ("failing_tests", "all_tests"):
            (workdir / name).unlink(missing_ok=True)
        return
    dirs: list[Path] = []
    if system == "gradle":
        dirs = list(workdir.glob("**/build/test-results"))
    elif system == "maven":
        dirs = (list(workdir.glob("**/target/surefire-reports"))
                + list(workdir.glob("**/target/failsafe-reports")))
    for d in dirs:
        shutil.rmtree(d, ignore_errors=True)


_BUILD_MARKERS = (
    "COMPILATION ERROR",
    "BUILD FAILURE",
    "FAILURE: Build failed",
    "cannot find symbol",
    "errors during collection",
    "collected 0 items",
    "error:",
)


def _build_fail_message(output: str, returncode: int) -> str:
    for marker in _BUILD_MARKERS:
        idx = output.find(marker)
        if idx != -1:
            line = output[idx:].splitlines()[0].strip()
            return f"build failed — {line[:160]}"
    return f"build/command failed before tests ran (exit {returncode})"


def _tool_missing(output: str, returncode: int, tool: str) -> bool:
    # Only the shell's own "command not found" (exit 127) or the explicit
    # "<tool>: ... not found" line counts. A loose "<tool>" + "not found"
    # anywhere would misclassify a real test failure (e.g. an assertion message
    # mentioning both) as an environment error and drop the pass/fail counts.
    low = output.lower()
    t = tool.lower()
    return (
        returncode == 127
        or f"{t}: command not found" in low
        or f"{t}: not found" in low
    )


def _parse_defects4j(failing_text: "str | None", all_tests_text: "str | None",
                     stdout: str) -> "tuple[int | None, int, list[str]]":
    """Pure grading of a `defects4j test` run → (passed|None, failed, failed_names).

    Defects4J writes `failing_tests` (one '--- <Class>::<method>' header per failure,
    followed by its stack trace) and, during execution, `all_tests` (one
    '<Class>::<method>' per executed test) into the checkout root — the authoritative
    verdict. Falls back to the stdout summary ('Failing tests: N' then '  - <name>'
    lines) when the files are absent. `passed` is None when the executed total is
    unknown (all_tests missing), so the caller trusts the process exit code instead."""
    names: list[str] = []
    if failing_text is not None:
        names = [l[3:].strip() for l in failing_text.splitlines()
                 if l.startswith("---") and l[3:].strip()]
    else:
        for l in stdout.splitlines():
            m = re.match(r"\s*-\s+([\w.$]+(?:::|#)[\w$]+)\s*$", l)
            if m:
                names.append(m.group(1))
    failed = len(names)
    total = None
    if all_tests_text is not None:
        total = sum(1 for l in all_tests_text.splitlines() if l.strip())
    passed = max(total - failed, 0) if total is not None else None
    return passed, failed, names


def _grade_defects4j(workdir: Path, output: str, rc: int, command: str,
                     duration: float) -> VerifyResult:
    """Grade a `defects4j test` run by its authoritative artifacts, bypassing the
    generic (gradle/maven JUnit-XML) path. failing_tests non-empty → failed;
    otherwise a clean exit → passed."""
    def _read(name: str) -> "str | None":
        p = workdir / name
        try:
            return p.read_text(errors="replace") if p.exists() else None
        except OSError:
            return None
    passed, failed, names = _parse_defects4j(_read("failing_tests"),
                                             _read("all_tests"), output)
    if failed > 0:
        total = (passed + failed) if passed is not None else failed
        return VerifyResult(
            status="failed", reason="tests_failed",
            message=f"{failed} of {total} relevant tests failed",
            command=command, duration_s=duration,
            passed_count=passed, failed_count=failed, failed_names=names,
            raw_output=output)
    if passed == 0:                       # all_tests present but empty → nothing ran
        return VerifyResult(
            status="error", reason="no_tests", message="no relevant tests were run",
            command=command, duration_s=duration, passed_count=0, failed_count=0,
            raw_output=output)
    if rc != 0:                           # no failing tests recorded but the run broke
        return VerifyResult(
            status="error", reason="build_failed",
            message=_build_fail_message(output, rc),
            command=command, duration_s=duration,
            passed_count=passed, failed_count=0, raw_output=output)
    return VerifyResult(
        status="passed", reason="passed",
        message=(f"{passed} relevant tests passed" if passed is not None
                 else "all relevant tests passed"),
        command=command, duration_s=duration,
        passed_count=passed, failed_count=0, raw_output=output)


def run_verify(workdir: Path, command: str, timeout_s: int,
               on_line: "Callable[[str], None] | None" = None) -> VerifyResult:
    """Run `command` from `workdir`, classify the outcome, keep the full output.

    ``on_line`` (optional) is called with each output line as it arrives, so a
    caller can tail live progress (e.g. baseline verify) without waiting for the
    whole run. The full output is still collected and parsed as before."""
    workdir = Path(workdir)
    started = time.time()
    parts = command.split()
    tool = parts[0] if parts else command

    # Clear any pre-existing JUnit XML results so the fallback below can only
    # read reports produced by this very invocation (closes a false-pass hole
    # where stale green reports from an agent's mid-task test run would be
    # misread as success after a final edit broke compilation).
    _system = _system_of(command)
    if _system is not None:
        _clear_results(workdir, _system)

    if on_line is None:
        # Fast path (no live tail needed): a single capture. This is the exact
        # prior behaviour the per-run/reverify callers and their tests rely on.
        try:
            completed = subprocess.run(
                command, shell=True, cwd=workdir,
                capture_output=True, text=True, timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return VerifyResult(
                status="timeout", reason="timeout",
                message=f"verify timed out after {timeout_s}s",
                command=command, duration_s=time.time() - started,
            )
        except FileNotFoundError as exc:
            return VerifyResult(
                status="error", reason="tool_not_found",
                message=f"{tool} not found on PATH",
                command=command, duration_s=time.time() - started, raw_output=str(exc),
            )
        output = (completed.stdout or "") + "\n" + (completed.stderr or "")
        rc = completed.returncode
    else:
        # Streaming path: tail lines live via on_line while collecting the full
        # output. A reader thread reads; the main thread enforces the timeout with
        # a hard kill (a hung download emits no lines, so the read loop alone can't
        # be trusted to honour the deadline).
        try:
            proc = subprocess.Popen(
                command, shell=True, cwd=workdir,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
        except FileNotFoundError as exc:
            return VerifyResult(
                status="error", reason="tool_not_found",
                message=f"{tool} not found on PATH",
                command=command, duration_s=time.time() - started, raw_output=str(exc),
            )
        chunks: list[str] = []

        def _reader() -> None:
            if proc.stdout is None:
                return
            for line in proc.stdout:
                chunks.append(line)
                try:
                    on_line(line.rstrip("\n"))
                except Exception:
                    pass

        reader = threading.Thread(target=_reader, daemon=True)
        reader.start()
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            reader.join(timeout=5)
            return VerifyResult(
                status="timeout", reason="timeout",
                message=f"verify timed out after {timeout_s}s",
                command=command, duration_s=time.time() - started,
                raw_output="".join(chunks),
            )
        reader.join(timeout=5)
        output = "".join(chunks)
        rc = proc.returncode
    duration = time.time() - started

    if _tool_missing(output, rc, tool):
        return VerifyResult(
            status="error", reason="tool_not_found",
            message=f"{tool} not found on PATH",
            command=command, duration_s=duration, raw_output=output,
        )

    # Defects4J grades by its own artifacts (failing_tests / all_tests), not by
    # gradle/maven JUnit XML — take the dedicated path with its own verdict.
    if _system_of(command) == "defects4j":
        return _grade_defects4j(workdir, output, rc, command, duration)

    parser = _parser_for(command)
    parsed: tuple[int, int, list[str]] | None = None
    if parser is not None:
        try:
            parsed = parser(output)
        except ValueError:
            parsed = None

    # Fall back to the JUnit XML test-results when the console output had no
    # parseable summary (modern Gradle on a green build, Maven -q, etc.). These
    # files are always written by the test task regardless of console verbosity.
    if parsed is None:
        system = _system_of(command)
        if system is not None:
            parsed = _parse_results_xml(workdir, system)

    if parsed is not None:
        passed, failed, names = parsed
        total = passed + failed
        if failed > 0:
            return VerifyResult(
                status="failed", reason="tests_failed",
                message=f"{failed} of {total} tests failed",
                command=command, duration_s=duration,
                passed_count=passed, failed_count=failed, failed_names=names,
                raw_output=output,
            )
        if total == 0:
            return VerifyResult(
                status="error", reason="no_tests", message="no tests were run",
                command=command, duration_s=duration,
                passed_count=0, failed_count=0, raw_output=output,
            )
        if rc == 0:
            return VerifyResult(
                status="passed", reason="passed",
                message=f"{passed} tests passed",
                command=command, duration_s=duration,
                passed_count=passed, failed_count=0, raw_output=output,
            )
        return VerifyResult(
            status="error", reason="build_failed",
            message=_build_fail_message(output, rc),
            command=command, duration_s=duration,
            passed_count=passed, failed_count=0, raw_output=output,
        )

    if rc != 0:
        return VerifyResult(
            status="error", reason="build_failed",
            message=_build_fail_message(output, rc),
            command=command, duration_s=duration, raw_output=output,
        )
    return VerifyResult(
        status="error", reason="unparseable",
        message="could not parse test output",
        command=command, duration_s=duration, raw_output=output,
    )


def write_verify_log(rundir: Path, v: VerifyResult) -> None:
    """Persist the full verify output with a small diagnostic header."""
    dur = f"{v.duration_s:.1f}s" if v.duration_s is not None else "—"
    header = (
        f"# command: {v.command}\n"
        f"# status: {v.status} ({v.reason})\n"
        f"# message: {v.message}\n"
        f"# duration: {dur}\n"
        f"───\n"
    )
    (Path(rundir) / "verify_output.log").write_text(header + (v.raw_output or ""))
