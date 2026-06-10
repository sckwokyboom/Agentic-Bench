# scripts/setup_check.py
"""Once-per-machine readiness check for Agentic-Bench (+ optional sandbox build).

Run from an ACTIVATED venv at the repo root:
  python scripts/setup_check.py [--container] [--build-image]
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

OK, BAD = "  [ok]", "  [!!]"
fails: list[str] = []


def check(name: str, ok: bool, hint: str) -> None:
    print(f"{OK if ok else BAD} {name}")
    if not ok:
        fails.append(f"{name}: {hint}")


def out_of(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True).stdout + \
               subprocess.run(cmd, capture_output=True, text=True).stderr
    except FileNotFoundError:
        return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--container", action="store_true")
    ap.add_argument("--build-image", action="store_true")
    a = ap.parse_args()

    check("python >= 3.10", sys.version_info >= (3, 10), "install newer python")
    try:
        import abench  # noqa: F401
        check("abench importable (venv active, pip install -e done)", True, "")
    except ImportError:
        check("abench importable", False, "python -m venv .venv; activate; pip install -e '.[dev]'")
    oc = shutil.which("opencode")
    ver = out_of(["opencode", "--version"]) if oc else ""
    check("opencode 1.15.x on PATH", bool(re.search(r"\b1\.15\.", ver)),
          "npm i -g opencode-ai")
    check("git on PATH", shutil.which("git") is not None, "install git")
    jver = out_of(["java", "-version"])
    m = re.search(r'version "(\d+)', jver)
    check("JDK 17-21 (java on PATH / JAVA_HOME)", bool(m and 17 <= int(m.group(1)) <= 21),
          "install Temurin 21 and set JAVA_HOME")
    if a.container:
        docker = shutil.which("docker") or shutil.which("podman")
        check("docker/podman", docker is not None, "install Docker Desktop (WSL2 on Windows)")
        if docker:
            have = subprocess.run([docker, "image", "inspect", "abench-sandbox:latest"],
                                  capture_output=True).returncode == 0
            if not have and a.build_image:
                subprocess.run([docker, "build", "-t", "abench-sandbox:latest",
                                "-f", "docker/Dockerfile.sandbox", "."], check=True)
                have = True
            check("abench-sandbox:latest image", have, "re-run with --build-image")
    if fails:
        print("\nFix these and re-run:\n- " + "\n- ".join(fails))
        return 1
    print("\nAll good.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
