import json
import shutil as _shutil
import subprocess
from pathlib import Path

import pytest

from abench.config import SandboxCfg
from abench.tool_validation import (
    ToolValidation,
    _build_probe_workdir,
    _parse_probe,
    _probe_command,
    validate_tool,
)


def test_parse_registered_when_tool_truthy_in_tools():
    out = json.dumps({"name": "abench", "tools": {"impact": True, "bash": True}})
    r = _parse_probe("impact", 0, out, "")
    assert isinstance(r, ToolValidation)
    assert r.registered is True
    assert r.errors == []
    assert r.tool_name == "impact"


def test_parse_not_registered_when_absent():
    out = json.dumps({"tools": {"bash": True}})
    r = _parse_probe("impact", 0, out, "")
    assert r.registered is False
    assert r.errors  # a human-readable "not present" message


def test_parse_build_error_on_nonzero_exit():
    stderr = ('ERROR 2026-06-15 service=default name=AggregateError '
              'message=4 errors building "/x/.opencode/tools/impact.ts" '
              'stack=AggregateError: 4 errors building "/x/.opencode/tools/impact.ts"')
    r = _parse_probe("impact", 1, "", stderr)
    assert r.registered is False
    assert r.exit_code == 1
    assert any("errors building" in e for e in r.errors)


def test_parse_unparseable_stdout_is_not_registered():
    r = _parse_probe("impact", 0, "not json", "")
    assert r.registered is False
    assert r.errors


def test_build_probe_workdir_lays_out_tool_and_config(tmp_path):
    tool = tmp_path / "echofile.ts"
    tool.write_text("export default {}\n")
    dest = tmp_path / "probe"
    out = _build_probe_workdir(tool, "abench", "deepseek/deepseek-chat", dest)
    assert out == dest
    copied = dest / ".opencode" / "tools" / "echofile.ts"
    assert copied.is_file()
    cfg = json.loads((dest / "opencode.json").read_text())
    assert "abench" in cfg["agent"]
    assert cfg["agent"]["abench"]["model"] == "deepseek/deepseek-chat"


def test_probe_command_host_mode():
    cmd = _probe_command(SandboxCfg(mode="none"), "/tmp/probe", "abench")
    assert cmd[:4] == ["opencode", "debug", "agent", "abench"]
    assert "--dir" not in cmd  # debug agent reads the project from cwd
    assert "docker" not in cmd and cmd[0] == "opencode"


def test_probe_command_container_mode_wraps_docker():
    sb = SandboxCfg(mode="container", image="abench-sandbox:latest",
                    runtime="docker", workdir_mount="/work")
    cmd = _probe_command(sb, "/tmp/probe", "abench")
    assert cmd[:3] == ["docker", "run", "--rm"]
    assert "-v" in cmd and "/tmp/probe:/work" in cmd
    assert "-w" in cmd and "/work" in cmd  # in-container cwd
    assert "abench-sandbox:latest" in cmd
    assert "opencode" in cmd and "debug" in cmd and "agent" in cmd
    assert "--dir" not in cmd


def test_validate_tool_orchestration_mocked(tmp_path, monkeypatch):
    """validate_tool builds a workdir, runs the probe, and parses — without a
    real opencode (subprocess.run is stubbed)."""
    tool = tmp_path / "impact.ts"
    tool.write_text("export default {}\n")

    class _CP:
        returncode = 0
        stdout = json.dumps({"tools": {"impact": True}})
        stderr = ""

    seen = {}

    def fake_run(cmd, capture_output, text, timeout, cwd=None):
        seen["cmd"] = cmd
        seen["cwd"] = cwd
        return _CP()

    monkeypatch.setattr(subprocess, "run", fake_run)
    r = validate_tool(tool, sandbox=SandboxCfg(mode="none"), agent="abench")
    assert r.registered is True
    assert seen["cmd"][:4] == ["opencode", "debug", "agent", "abench"]


@pytest.mark.skipif(_shutil.which("opencode") is None, reason="opencode not on PATH")
def test_validate_tool_integration_good_and_broken(tmp_path):
    """Real opencode: a valid tool registers; a broken one does not."""
    good = tmp_path / "echo_probe.ts"
    good.write_text(
        'import { tool } from "@opencode-ai/plugin"\n'
        'export default tool({ description: "x", args: {}, '
        'async execute() { return "ok" } })\n')
    rg = validate_tool(good, sandbox=SandboxCfg(mode="none"), agent="abench")
    assert rg.registered is True, rg.errors

    bad = tmp_path / "broken_probe.ts"
    bad.write_text('import { tool } from "@opencode-ai/plugin"\n'
                   'export default tool({ this is not valid {{{\n')
    rb = validate_tool(bad, sandbox=SandboxCfg(mode="none"), agent="abench")
    assert rb.registered is False
    assert rb.errors
