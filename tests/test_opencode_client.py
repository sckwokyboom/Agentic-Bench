# tests/test_opencode_client.py
import json
import subprocess
import threading
import time

from abench.config import OpenCodeCfg, ProviderCfg, SandboxCfg
from abench.opencode_client import RealOpenCodeClient, build_run_command


class _StderrChatterProc:
    """A hung request that still LOGS: emits stderr lines forever but never any
    stdout (model) event. `.wait` blocks until killed. Used to prove the stall
    watchdog keys off model output (stdout), not stderr noise."""
    def __init__(self):
        self.returncode = None
        self._killed = threading.Event()
        self.stdout = iter(())                       # no model output, ever
        self.stderr = self._chatter()

    def _chatter(self):
        while not self._killed.is_set():
            time.sleep(0.01)
            yield b"INFO  service=api waiting for response\n"

    def wait(self, timeout=None):
        end = time.time() + (timeout or 0)
        while time.time() < end:
            if self._killed.is_set():
                self.returncode = -9
                return -9
            time.sleep(0.01)
        raise subprocess.TimeoutExpired(cmd="opencode", timeout=timeout)

    def kill(self):
        self._killed.set()
        self.returncode = -9


def test_stall_watchdog_ignores_stderr_noise(tmp_path, monkeypatch):
    # The real 62h-hang cause: opencode kept logging to stderr while the request
    # hung, so a watchdog counting ANY output never fired. The watchdog must key
    # off MODEL output (stdout events) only — so a stderr-chattering-but-tokenless
    # run is caught as stalled. idle_timeout 1s fires well before the 6s backstop
    # deadline; a regression (stderr resets the clock) would instead time out at 6s.
    import abench.opencode_client as oc
    monkeypatch.setattr(oc.subprocess, "Popen",
                        lambda *a, **k: _StderrChatterProc())
    client = RealOpenCodeClient(OpenCodeCfg(idle_timeout_s=1, stall_retries=0))
    wd = tmp_path / "wd"; wd.mkdir()
    res = client.run_task(workdir=str(wd), system_prompt="s", model="m",
                          user_message="go", timeout_s=6, on_event=lambda e: None)
    assert res.trace.interrupted_reason == "stalled"    # NOT "timeout"


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


def _stub_attempts(client, monkeypatch, reasons):
    """Make _run_attempt return the given interrupted_reasons in order (a fake
    attempt each), recording how many times it was called. Lets us drive the
    run_task retry loop without spawning opencode."""
    calls = []
    it = iter(reasons)

    def fake_attempt(**_kw):
        reason = next(it)
        calls.append(reason)
        return [], reason, (0 if reason is None else 1)

    monkeypatch.setattr(client, "_run_attempt", fake_attempt)
    return calls


def test_run_task_retries_a_stalled_attempt_then_succeeds(tmp_path, monkeypatch):
    # A hung request (stalled) is dropped and relaunched; the next attempt that
    # doesn't stall ends the loop. stall_retries=2 → up to 3 attempts.
    client = RealOpenCodeClient(OpenCodeCfg(stall_retries=2))
    calls = _stub_attempts(client, monkeypatch, ["stalled", "stalled", None])
    wd = tmp_path / "wd"; wd.mkdir()
    res = client.run_task(workdir=str(wd), system_prompt="s", model="m",
                          user_message="go", timeout_s=1, on_event=lambda e: None)
    assert calls == ["stalled", "stalled", None]      # retried twice, then succeeded
    assert res.trace.interrupted_reason is None        # final attempt won


def test_run_task_gives_up_after_stall_retries(tmp_path, monkeypatch):
    # Every attempt stalls → drop stall_retries+1 times total, then surface stalled.
    client = RealOpenCodeClient(OpenCodeCfg(stall_retries=2))
    calls = _stub_attempts(client, monkeypatch, ["stalled", "stalled", "stalled"])
    wd = tmp_path / "wd"; wd.mkdir()
    res = client.run_task(workdir=str(wd), system_prompt="s", model="m",
                          user_message="go", timeout_s=1, on_event=lambda e: None)
    assert calls == ["stalled", "stalled", "stalled"]  # 1 initial + 2 retries
    assert res.trace.interrupted_reason == "stalled"


def test_run_task_no_retry_when_stall_retries_zero(tmp_path, monkeypatch):
    client = RealOpenCodeClient(OpenCodeCfg(stall_retries=0))
    calls = _stub_attempts(client, monkeypatch, ["stalled", None])  # 2nd never used
    wd = tmp_path / "wd"; wd.mkdir()
    res = client.run_task(workdir=str(wd), system_prompt="s", model="m",
                          user_message="go", timeout_s=1, on_event=lambda e: None)
    assert calls == ["stalled"]                        # dropped once, no retry
    assert res.trace.interrupted_reason == "stalled"


def test_run_task_does_not_retry_non_stall_interruptions(tmp_path, monkeypatch):
    # A timeout / cancel / error is NOT a transient transport stall — never retried.
    client = RealOpenCodeClient(OpenCodeCfg(stall_retries=3))
    calls = _stub_attempts(client, monkeypatch, ["timeout", None])
    wd = tmp_path / "wd"; wd.mkdir()
    res = client.run_task(workdir=str(wd), system_prompt="s", model="m",
                          user_message="go", timeout_s=1, on_event=lambda e: None)
    assert calls == ["timeout"]                        # stopped immediately
    assert res.trace.interrupted_reason == "timeout"


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


def test_build_run_command_names_container_for_cancellation():
    cfg = OpenCodeCfg(sandbox=SandboxCfg(mode="container"))
    argv = build_run_command(cfg, workdir="/w", model="m", user_message="go",
                             config_data={}, container_name="abench-oc-deadbeef")
    assert argv[argv.index("--name") + 1] == "abench-oc-deadbeef"   # killable by name
    # no name -> no --name (back-compat)
    argv2 = build_run_command(cfg, workdir="/w", model="m", user_message="go", config_data={})
    assert "--name" not in argv2
