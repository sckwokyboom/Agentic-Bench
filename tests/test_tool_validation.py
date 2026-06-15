import json
from pathlib import Path

from abench.config import SandboxCfg
from abench.tool_validation import (
    ToolValidation,
    _build_probe_workdir,
    _parse_probe,
    _probe_command,
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
    assert "--dir" in cmd and "/tmp/probe" in cmd
    assert "docker" not in cmd and "run" not in cmd[:2]


def test_probe_command_container_mode_wraps_docker():
    sb = SandboxCfg(mode="container", image="abench-sandbox:latest",
                    runtime="docker", workdir_mount="/work")
    cmd = _probe_command(sb, "/tmp/probe", "abench")
    assert cmd[:3] == ["docker", "run", "--rm"]
    assert "-v" in cmd and "/tmp/probe:/work" in cmd
    assert "abench-sandbox:latest" in cmd
    # inner command targets the in-container mount, not the host path
    assert "opencode" in cmd and "/work" in cmd
    assert "/tmp/probe" not in cmd[cmd.index("abench-sandbox:latest"):]
