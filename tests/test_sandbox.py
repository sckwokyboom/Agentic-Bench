"""ensure_image: zero-touch sandbox image prep (auto-build on first use)."""
import subprocess
from pathlib import Path

import pytest

from abench import sandbox
from abench.config import SandboxCfg


class _FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _patch(monkeypatch, *, which="/usr/bin/docker", inspect_rc=0,
           build_rc=0, build_stderr=""):
    """Stub shutil.which + subprocess.run; record build invocations."""
    calls: list[list[str]] = []
    monkeypatch.setattr(sandbox.shutil, "which", lambda _name: which)

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[1:3] == ["image", "inspect"]:
            return _FakeProc(returncode=inspect_rc)
        if argv[1] == "build":
            return _FakeProc(returncode=build_rc, stderr=build_stderr)
        return _FakeProc()

    monkeypatch.setattr(sandbox.subprocess, "run", fake_run)
    return calls


def test_noop_when_mode_none(monkeypatch):
    calls = _patch(monkeypatch)
    sandbox.ensure_image(SandboxCfg(mode="none"))
    assert calls == []  # nothing touched


def test_skips_build_when_image_present(monkeypatch):
    calls = _patch(monkeypatch, inspect_rc=0)  # inspect succeeds → image exists
    sandbox.ensure_image(SandboxCfg(mode="container"))
    assert not any(c[1] == "build" for c in calls)


def test_builds_when_image_missing(monkeypatch, tmp_path):
    df = tmp_path / "Dockerfile"
    df.write_text("FROM scratch\n")
    calls = _patch(monkeypatch, inspect_rc=1)  # inspect fails → missing
    phases: list[dict] = []
    sandbox.ensure_image(
        SandboxCfg(mode="container", image="img:1", runtime="podman",
                   dockerfile=str(df)),
        progress=phases.append,
    )
    build = next(c for c in calls if c[1] == "build")
    assert build[0] == "podman"
    assert build[:4] == ["podman", "build", "-t", "img:1"]
    assert "-f" in build and str(df) in build
    # surfaced a progress phase for the UI
    assert any(p["phase"] == "building_sandbox_image" for p in phases)


def test_runtime_missing_raises(monkeypatch):
    _patch(monkeypatch, which=None)
    with pytest.raises(sandbox.SandboxError, match="not found on PATH"):
        sandbox.ensure_image(SandboxCfg(mode="container"))


def test_missing_image_with_autobuild_off_raises(monkeypatch):
    _patch(monkeypatch, inspect_rc=1)
    with pytest.raises(sandbox.SandboxError, match="auto_build is off"):
        sandbox.ensure_image(SandboxCfg(mode="container", auto_build=False))


def test_missing_dockerfile_raises(monkeypatch):
    _patch(monkeypatch, inspect_rc=1)
    with pytest.raises(sandbox.SandboxError, match="Dockerfile not found"):
        sandbox.ensure_image(
            SandboxCfg(mode="container", dockerfile="/no/such/Dockerfile"))


def test_build_failure_raises_with_output(monkeypatch, tmp_path):
    df = tmp_path / "Dockerfile"
    df.write_text("FROM scratch\n")
    _patch(monkeypatch, inspect_rc=1, build_rc=1, build_stderr="boom: no space")
    with pytest.raises(sandbox.SandboxError, match="boom: no space"):
        sandbox.ensure_image(
            SandboxCfg(mode="container", dockerfile=str(df)))


def test_bundled_dockerfile_exists():
    # The default Dockerfile the auto-build resolves to must ship with the repo.
    assert sandbox._DEFAULT_DOCKERFILE.is_file()
