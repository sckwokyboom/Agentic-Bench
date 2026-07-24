"""Sandbox image management for container-mode runs.

Keeps the container path zero-touch: on first use the bench checks the runtime
is present and builds the image from the bundled Dockerfile if it's missing, so
the operator only has to set ``opencode.sandbox.mode: container``.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable

from .config import SandboxCfg

# Bundled Dockerfile: <repo>/docker/Dockerfile.sandbox (abench/ is one level in).
_DEFAULT_DOCKERFILE = Path(__file__).resolve().parent.parent / "docker" / "Dockerfile.sandbox"


class SandboxError(RuntimeError):
    """Raised when the sandbox runtime/image cannot be prepared."""


def _resolve_dockerfile(sb: SandboxCfg) -> Path:
    return Path(sb.dockerfile) if sb.dockerfile else _DEFAULT_DOCKERFILE


def _image_exists(runtime: str, image: str) -> bool:
    try:
        proc = subprocess.run(
            [runtime, "image", "inspect", image],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return False
    return proc.returncode == 0


def ensure_image(
    sb: SandboxCfg,
    *,
    log: Callable[[str], None] = lambda _m: None,
    progress: Callable[[dict], None] | None = None,
) -> None:
    """Ensure the sandbox image is ready before any run (no-op unless container
    mode). Builds it once from the Dockerfile when missing and auto_build is on.

    Raises :class:`SandboxError` with an actionable message when the runtime is
    absent, the image is missing with auto_build off, the Dockerfile is missing,
    or the build fails.
    """
    if sb.mode != "container":
        return

    if shutil.which(sb.runtime) is None:
        raise SandboxError(
            f"container runtime '{sb.runtime}' not found on PATH — install it "
            f"or set opencode.sandbox.runtime (docker|podman)."
        )

    if _image_exists(sb.runtime, sb.image):
        return

    if not sb.auto_build:
        raise SandboxError(
            f"sandbox image '{sb.image}' not found and auto_build is off — "
            f"build it manually or enable opencode.sandbox.auto_build."
        )

    dockerfile = _resolve_dockerfile(sb)
    if not dockerfile.is_file():
        raise SandboxError(f"sandbox Dockerfile not found: {dockerfile}")

    if progress is not None:
        progress({
            "phase": "building_sandbox_image",
            "message": (
                f"Building sandbox image {sb.image} (first run only — this can "
                f"take a few minutes)…"
            ),
        })
    log(f"[abench] building sandbox image {sb.image} from {dockerfile}")

    # Dockerfile.sandbox COPYs from the repo (docker/extra-ca, docker/*.sh/*.py,
    # docker/runtime-probe, experiments/.../stripped); the repo-root .dockerignore
    # trims the context to just those. Build from the repo root so those COPYs
    # resolve — an empty context makes every COPY fail (first at docker/extra-ca).
    ctx = str(Path(__file__).resolve().parent.parent)
    proc = subprocess.run(
        [sb.runtime, "build", "-t", sb.image, "-f", str(dockerfile), ctx],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-20:]
        raise SandboxError(
            f"failed to build sandbox image '{sb.image}' (exit {proc.returncode}):\n"
            + "\n".join(tail)
        )
    log(f"[abench] sandbox image {sb.image} ready")
