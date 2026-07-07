# scripts/setup_check.py
"""Once-per-machine readiness check for Agentic-Bench (+ optional sandbox build).

Run from an ACTIVATED venv at the repo root:
  python scripts/setup_check.py [--container] [--build-image]
"""
from __future__ import annotations

import argparse
import os
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


def _proxy_build_args() -> list[str]:
    """Inherit the host's proxy env into `docker build` so apt/gradle/maven/npm can
    fetch through a corporate proxy on an isolated host. Passed as BUILD-ARGS (build-time
    only — unlike ENV they are NOT baked into the runtime image, so a `run` is never
    forced through the proxy and your model endpoint stays reachable). Also derives
    JAVA_TOOL_OPTIONS with JVM proxy sysprops, because Gradle's wrapper download and
    dependency fetch ignore the http_proxy env and need -Dhttps.proxyHost. No proxy in
    the environment → returns [] (a normal direct build, unchanged)."""
    from urllib.parse import urlparse
    names = ["HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
             "http_proxy", "https_proxy", "no_proxy"]
    present = {n: os.environ[n] for n in names if os.environ.get(n)}
    if not present:
        return []
    args: list[str] = ["--network=host"]
    for n, v in present.items():
        args += ["--build-arg", f"{n}={v}"]
    hp = (present.get("HTTPS_PROXY") or present.get("https_proxy")
          or present.get("HTTP_PROXY") or present.get("http_proxy"))
    u = urlparse(hp if "://" in hp else f"http://{hp}")
    if u.hostname and u.port:
        opts = (f"-Dhttps.proxyHost={u.hostname} -Dhttps.proxyPort={u.port} "
                f"-Dhttp.proxyHost={u.hostname} -Dhttp.proxyPort={u.port}")
        np = present.get("NO_PROXY") or present.get("no_proxy")
        hosts = "|".join(h.strip() for h in (np or "").split(",") if h.strip())
        if hosts:
            opts += f" -Dhttp.nonProxyHosts={hosts} -Dhttps.nonProxyHosts={hosts}"
        args += ["--build-arg", f"JAVA_TOOL_OPTIONS={opts}"]
    return args


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
    # prepare.py runs the JDK from JAVA_HOME, so check THAT java when set —
    # not whatever happens to be first on PATH.
    java_home = os.environ.get("JAVA_HOME")
    java_bin = str(Path(java_home) / "bin" / "java") if java_home else "java"
    jver = out_of([java_bin, "-version"])
    m = re.search(r'version "(\d+)', jver)
    src = "JAVA_HOME" if java_home else "PATH"
    # 21 is the single safe target: the GT CLI is built by a toolchain pinned to
    # 21 (so it CANNOT run on 17–20), and picocli's gradle 8.14 tops out at 24.
    check(f"JDK 21–24 ({src} java; 21 recommended)",
          bool(m and 21 <= int(m.group(1)) <= 24),
          "install Temurin 21 and point JAVA_HOME at it")
    if a.container:
        docker = shutil.which("docker") or shutil.which("podman")
        check("docker/podman", docker is not None, "install Docker Desktop (WSL2 on Windows)")
        if docker:
            have = subprocess.run([docker, "image", "inspect", "abench-sandbox:latest"],
                                  capture_output=True).returncode == 0
            if not have and a.build_image:
                proxy = _proxy_build_args()
                if proxy:
                    print("  [setup] inheriting host proxy into docker build "
                          "(build-time only): " + " ".join(proxy))
                subprocess.run([docker, "build", *proxy, "-t", "abench-sandbox:latest",
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
