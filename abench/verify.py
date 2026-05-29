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
    command: str | None = None
    duration_s: float | None = None
    passed_count: int | None = None
    failed_count: int | None = None
    failed_names: list[str] = field(default_factory=list)
    raw_output: str = ""


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


def run_verify(workdir: Path, command: str, timeout_s: int) -> VerifyResult:
    """Run `command` from `workdir`. Parse output. Return a structured result."""
    workdir = Path(workdir)
    started = time.time()
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return VerifyResult(
            status="timeout",
            command=command,
            duration_s=time.time() - started,
        )
    except FileNotFoundError as exc:
        return VerifyResult(
            status="error",
            command=command,
            duration_s=time.time() - started,
            raw_output=str(exc),
        )

    output = completed.stdout + "\n" + completed.stderr
    duration = time.time() - started
    parser = _parser_for(command)
    if parser is None:
        return VerifyResult(
            status="error",
            command=command,
            duration_s=duration,
            raw_output=output[:8000],
        )
    try:
        passed, failed, names = parser(output)
    except ValueError:
        return VerifyResult(
            status="error",
            command=command,
            duration_s=duration,
            raw_output=output[:8000],
        )

    status: Status
    if completed.returncode != 0 and failed == 0:
        return VerifyResult(
            status="error",
            command=command,
            duration_s=duration,
            passed_count=passed,
            failed_count=failed,
            failed_names=names,
            raw_output=output[:8000],
        )
    status = "passed" if failed == 0 else "failed"
    return VerifyResult(
        status=status,
        command=command,
        duration_s=duration,
        passed_count=passed,
        failed_count=failed,
        failed_names=names,
    )
