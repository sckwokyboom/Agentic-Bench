# tests/test_opencode_client.py
import json

from abench.config import OpenCodeCfg, ProviderCfg, SandboxCfg
from abench.opencode_client import RealOpenCodeClient, build_run_command


class _FakeProc:
    """Minimal stand-in for subprocess.Popen: no output, exits 0 immediately."""
    def __init__(self):
        self.returncode = 0
        self.stdout = iter(())
        self.stderr = iter(())

    def wait(self, timeout=None):
        self.returncode = 0
        return 0

    def poll(self):
        return 0

    def kill(self):
        pass


def test_run_task_injects_authjson_key_into_env(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    authdir = tmp_path / "opencode"
    authdir.mkdir(parents=True)
    (authdir / "auth.json").write_text(
        json.dumps({"deepseek": {"type": "api", "key": "sk-secret"}}))

    captured = {}
    import abench.opencode_client as oc

    def fake_popen(cmd, stdout, stderr, cwd, env):
        captured["env"] = env
        return _FakeProc()

    monkeypatch.setattr(oc.subprocess, "Popen", fake_popen)
    # No session export expected (no events) — fail loudly if it tries.
    monkeypatch.setattr(
        oc.subprocess, "run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no export expected")))

    cfg = OpenCodeCfg(providers=[ProviderCfg(
        id="deepseek", base_url="https://api.deepseek.com/v1",
        models=["deepseek-chat"], api_key_env="DEEPSEEK_API_KEY")])
    client = RealOpenCodeClient(cfg, timeout_s=None)
    wd = tmp_path / "wd"
    wd.mkdir()
    client.run_task(workdir=str(wd), system_prompt="s",
                    model="deepseek/deepseek-chat", user_message="go",
                    timeout_s=None, on_event=lambda e: None)
    assert captured["env"]["DEEPSEEK_API_KEY"] == "sk-secret"


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
