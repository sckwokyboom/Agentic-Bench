import json
import subprocess

from abench.config import ProviderCfg, SandboxCfg
from abench.reachability import ReachabilityResult, _probe_command, validate_reachability

PROV = ProviderCfg(id="deepseek", base_url="https://api.deepseek.com/v1",
                   models=["deepseek-chat"], api_key_env="DEEPSEEK_API_KEY")


def test_probe_command_host():
    cmd = _probe_command(SandboxCfg(mode="none"), PROV, "deepseek-chat", "/p/model_probe.py")
    assert cmd[0] == "python3" and cmd[1] == "/p/model_probe.py"
    assert cmd[2:] == ["https://api.deepseek.com/v1", "deepseek-chat", "DEEPSEEK_API_KEY"]


def test_probe_command_container_mounts_probe_and_names_key():
    sb = SandboxCfg(mode="container", image="abench-sandbox:latest", runtime="docker")
    cmd = _probe_command(sb, PROV, "deepseek-chat", "/p/model_probe.py")
    assert cmd[:3] == ["docker", "run", "--rm"]
    assert "-e" in cmd and "DEEPSEEK_API_KEY" in cmd       # name-only forward
    assert "/p/model_probe.py:/probe.py:ro" in cmd          # probe mounted
    assert "abench-sandbox:latest" in cmd
    assert "/probe.py" in cmd                                # in-container probe path
    assert all("Bearer" not in str(a) for a in cmd)


def test_validate_reachability_parses_probe_json(monkeypatch):
    class _CP:
        returncode = 0
        stdout = json.dumps({"reachable": True, "reason": "ok", "detail": ""})
        stderr = ""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _CP())
    r = validate_reachability(PROV, "deepseek-chat", sandbox=SandboxCfg(mode="none"))
    assert isinstance(r, ReachabilityResult)
    assert r.reachable is True and r.reason == "ok"


def test_validate_reachability_probe_failed_on_garbage(monkeypatch):
    class _CP:
        returncode = 1
        stdout = "not json"
        stderr = "boom"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _CP())
    r = validate_reachability(PROV, "deepseek-chat", sandbox=SandboxCfg(mode="none"))
    assert r.reachable is False and r.reason == "probe_failed"


def test_validate_reachability_isolated_probes_with_session_key(monkeypatch):
    """Isolated: the probe env carries THIS visitor's session key, and the
    operator's env var is overwritten so it can't make a bad key look reachable."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-operator")     # operator env present
    captured = {}

    class _CP:
        returncode = 0
        stdout = json.dumps({"reachable": True, "reason": "ok", "detail": ""})
        stderr = ""

    def fake_run(*a, **k):
        captured["env"] = k.get("env")
        return _CP()

    monkeypatch.setattr(subprocess, "run", fake_run)
    validate_reachability(PROV, "deepseek-chat", sandbox=SandboxCfg(mode="none"),
                          session_keys={"deepseek": "sk-visitor"}, isolated=True)
    assert captured["env"]["DEEPSEEK_API_KEY"] == "sk-visitor"   # not sk-operator


def test_key_never_in_probe_command_argv():
    """The key VALUE must never appear in argv — only the env NAME is forwarded."""
    sb = SandboxCfg(mode="container", image="abench-sandbox:latest", runtime="docker")
    cmd = _probe_command(sb, PROV, "deepseek-chat", "/p/model_probe.py")
    SECRET = "sk-THIS-MUST-NOT-LEAK"
    assert all(SECRET not in str(a) for a in cmd)


def test_result_has_no_key_field():
    r = ReachabilityResult(False, "auth", "scrubbed")
    assert not hasattr(r, "key") and "key" not in r.__dict__
