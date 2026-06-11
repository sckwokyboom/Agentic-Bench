# tests/test_opencode_client.py
import json

from abench.config import OpenCodeCfg, SandboxCfg
from abench.opencode_client import build_run_command


def test_build_run_command_resolves_lib_mount(tmp_path, monkeypatch):
    reg = tmp_path / ".abench.local.json"
    reg.write_text(json.dumps({"libraries": {"graph-tipper": "/host/gt"}}))
    monkeypatch.setenv("ABENCH_LOCAL_CONFIG", str(reg))
    cfg = OpenCodeCfg(sandbox=SandboxCfg(
        mode="container",
        cache_mounts=["{lib:graph-tipper}:/opt/graph-tipper:ro"]))
    argv = build_run_command(cfg, workdir="/w", model="m",
                             user_message="go", config_data={})
    assert "/host/gt:/opt/graph-tipper:ro" in argv
