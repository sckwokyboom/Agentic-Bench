# tests/test_sandbox_entrypoint.py
"""Verify the sandbox entrypoint's tool-install logic without building the image
(paths overridden via GT_TOOLS/DEST; "true" stands in for the real CMD)."""
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "docker" / "sandbox-entrypoint.sh"


def test_installs_tools_from_mounted_gt(tmp_path):
    gt_tools = tmp_path / "gt" / "integrations" / "opencode" / "tools"
    gt_tools.mkdir(parents=True)
    (gt_tools / "impact.ts").write_text("x")
    (gt_tools / "crash_slice.ts").write_text("x")
    dest = tmp_path / "dest"
    env = {**os.environ, "GT_TOOLS": str(gt_tools), "DEST": str(dest)}
    r = subprocess.run(["sh", str(SCRIPT), "true"], env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert {p.name for p in dest.glob("*.ts")} == {"impact.ts", "crash_slice.ts"}
    assert "installed 2" in r.stderr


def test_noop_when_no_gt(tmp_path):
    dest = tmp_path / "dest"
    env = {**os.environ, "GT_TOOLS": str(tmp_path / "absent"), "DEST": str(dest)}
    r = subprocess.run(["sh", str(SCRIPT), "true"], env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert not dest.exists()
