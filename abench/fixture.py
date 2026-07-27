# abench/fixture.py
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

# Ephemeral identity passed per-command; does NOT touch user/global git config.
_GIT_ID = ["-c", "user.name=abench", "-c", "user.email=abench@local"]

# Artifacts opencode writes INTO the workdir (workdir-local config + state).
# They must never pollute the agent's "final source diff".
OPENCODE_ARTIFACTS = ("opencode.json", ".opencode")

# Tool runtime caches written into the workdir mid-session (e.g. the GT impact
# tool's .impact/) — never agent source changes.
RUNTIME_ARTIFACTS = (".impact",)

_TMPL_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _render_tmpl(text: str, env: dict[str, str], origin: str) -> str:
    missing = sorted({m.group(1) for m in _TMPL_VAR.finditer(text)} - set(env))
    if missing:
        raise RuntimeError(f"overlay template {origin}: undefined ${{...}} vars: {', '.join(missing)}")
    return _TMPL_VAR.sub(lambda m: env[m.group(1)], text)


def _apply_overlay(workdir: Path, overlay_dir: Path, env: dict[str, str]) -> None:
    if not Path(overlay_dir).is_dir():
        raise RuntimeError(f"overlay dir not found: {overlay_dir}")
    for item in sorted(Path(overlay_dir).rglob("*")):
        rel = item.relative_to(overlay_dir)
        if item.is_symlink():
            raise RuntimeError(f"overlay contains a symlink: {rel} — materialize it (symlinked dirs would copy empty)")
        if item.is_dir():
            (workdir / rel).mkdir(parents=True, exist_ok=True)
            continue
        dst = workdir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if item.name.endswith(".tmpl"):
            rendered = _render_tmpl(item.read_text(encoding="utf-8"), env, str(rel))
            dst.with_name(dst.name[: -len(".tmpl")]).write_text(rendered, encoding="utf-8")
        else:
            shutil.copy2(item, dst)


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


def _git_init_commit(workdir: Path, message: str = "fixture") -> str:
    """Init a git repo in `workdir`, commit everything, return the HEAD sha.

    Extracted from create_workdir so benchmark mode's run loop (added later in
    Plan 2) can reuse the same "materialized dir -> committed workdir" step."""
    subprocess.run(["git", "init", "-q"], cwd=workdir, check=True)
    subprocess.run(["git", "add", "-A"], cwd=workdir, check=True)
    subprocess.run(["git", *_GIT_ID, "commit", "-q", "-m", message],
                   cwd=workdir, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=workdir,
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def create_workdir(fixture_path: Path, parent: Path | None = None,
                   overlay_dir: Path | None = None,
                   overlay_env: dict[str, str] | None = None) -> tuple[Path, str]:
    fixture_path = Path(fixture_path)
    workdir = Path(tempfile.mkdtemp(prefix="abench-", dir=parent))
    try:
        _copy_tree(fixture_path, workdir)

        git_dir = workdir / ".git"
        if git_dir.exists():
            shutil.rmtree(git_dir)
        if (workdir / ".git").exists():  # leak guard
            raise RuntimeError("failed to strip .git from workdir")

        if overlay_dir is not None:
            _apply_overlay(workdir, Path(overlay_dir), overlay_env or {})

        sha = _git_init_commit(workdir)
        return workdir, sha
    except BaseException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise


def diff_workdir(workdir: Path) -> str:
    workdir = Path(workdir)
    subprocess.run(["git", "add", "-A"], cwd=workdir, check=True)
    # Exclude opencode's own artifacts AND build output via pathspecs (each its
    # own argv element) so the returned diff is ONLY real source changes the agent
    # made. Build dirs (target/, build/) matter here for two reasons: they are not
    # a "source change", and when the agent runs mvn/gradle they fill with binary
    # .class files and latin-1 resources whose bytes break a strict-UTF-8 decode of
    # the diff (a run that otherwise SUCCEEDED then crashes on patch capture).
    result = subprocess.run(
        ["git", "diff", "--cached", "HEAD", "--",
         ".",
         ":(exclude)opencode.json",
         ":(exclude).opencode",
         ":(exclude).opencode/**",
         ":(exclude).impact",
         ":(exclude).impact/**",
         ":(exclude)target",
         ":(exclude)target/**",
         ":(exclude)build",
         ":(exclude)build/**",
         ":(exclude)**/*.class"],
        cwd=workdir, capture_output=True,
        # errors="replace": a diff is metadata (diffstat, patch record); a stray
        # non-UTF-8 byte from a binary/legacy-encoded file must never abort the run.
        encoding="utf-8", errors="replace", check=True,
    )
    return result.stdout


def made_source_changes(workdir: Path) -> bool:
    """True iff the agent changed real source (excludes opencode artifacts)."""
    return bool(diff_workdir(workdir).strip())


def cleanup(workdir: Path) -> None:
    shutil.rmtree(workdir, ignore_errors=True)
