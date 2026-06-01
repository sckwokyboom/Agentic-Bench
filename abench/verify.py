"""Post-run verification — runs the project's test suite and parses the result."""
from __future__ import annotations

import subprocess
import time
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


def detect_command(workdir: Path) -> str | None:
    """Heuristic — return the canonical test command for this project, or None."""
    workdir = Path(workdir)
    if (workdir / "pom.xml").exists():
        if (workdir / "mvnw").exists():
            return "./mvnw test"
        return "mvn test"
    if (workdir / "build.gradle").exists() or (workdir / "build.gradle.kts").exists():
        if (workdir / "gradlew").exists():
            return "./gradlew test"
        return "gradle test"
    if (workdir / "pyproject.toml").exists() and (workdir / "tests").is_dir():
        return "pytest"
    return None


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
