# abench/fixture.py
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

# Ephemeral identity passed per-command; does NOT touch user/global git config.
_GIT_ID = ["-c", "user.name=abench", "-c", "user.email=abench@local"]

# Artifacts opencode writes INTO the workdir (workdir-local config + state).
# They must never pollute the agent's "final source diff".
OPENCODE_ARTIFACTS = ("opencode.json", ".opencode")


def _copy_tree(src: Path, dst: Path) -> None:
    # Try APFS copy-on-write clone (fast, cheap on macOS); fall back to shutil.
    try:
        subprocess.run(
            ["cp", "-c", "-R", f"{src}/.", str(dst)],
            check=True, stderr=subprocess.DEVNULL,
        )
        return
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def create_workdir(fixture_path: Path, parent: Path | None = None) -> tuple[Path, str]:
    fixture_path = Path(fixture_path)
    workdir = Path(tempfile.mkdtemp(prefix="abench-", dir=parent))
    _copy_tree(fixture_path, workdir)

    git_dir = workdir / ".git"
    if git_dir.exists():
        shutil.rmtree(git_dir)
    if (workdir / ".git").exists():  # leak guard
        raise RuntimeError("failed to strip .git from workdir")

    subprocess.run(["git", "init", "-q"], cwd=workdir, check=True)
    subprocess.run(["git", "add", "-A"], cwd=workdir, check=True)
    subprocess.run(["git", *_GIT_ID, "commit", "-q", "-m", "fixture"],
                   cwd=workdir, check=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=workdir,
                         capture_output=True, text=True, check=True).stdout.strip()
    return workdir, sha


def diff_workdir(workdir: Path) -> str:
    workdir = Path(workdir)
    subprocess.run(["git", "add", "-A"], cwd=workdir, check=True)
    # Exclude opencode's own artifacts via pathspecs (each its own argv element)
    # so the returned diff is ONLY real source changes the agent made.
    result = subprocess.run(
        ["git", "diff", "--cached", "HEAD", "--",
         ".",
         ":(exclude)opencode.json",
         ":(exclude).opencode",
         ":(exclude).opencode/**"],
        cwd=workdir, capture_output=True, text=True, check=True,
    )
    return result.stdout


def made_source_changes(workdir: Path) -> bool:
    """True iff the agent changed real source (excludes opencode artifacts)."""
    return bool(diff_workdir(workdir).strip())


def cleanup(workdir: Path) -> None:
    shutil.rmtree(workdir, ignore_errors=True)
