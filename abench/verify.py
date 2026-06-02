"""Post-run verification — runs the project's test suite and parses the result."""
from __future__ import annotations

import subprocess
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


def _parser_for(command: str) -> Callable[[str], tuple[int, int, list[str]]] | None:
    first = command.split()[0]
    return _PARSER_BY_PREFIX.get(first)


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
    return None


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


def run_verify(workdir: Path, command: str, timeout_s: int) -> VerifyResult:
    """Run `command` from `workdir`, classify the outcome, keep the full output."""
    workdir = Path(workdir)
    started = time.time()
    parts = command.split()
    tool = parts[0] if parts else command
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
    duration = time.time() - started
    rc = completed.returncode

    if _tool_missing(output, rc, tool):
        return VerifyResult(
            status="error", reason="tool_not_found",
            message=f"{tool} not found on PATH",
            command=command, duration_s=duration, raw_output=output,
        )

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
