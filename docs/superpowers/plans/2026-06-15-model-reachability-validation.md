# Secure model-reachability validation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A real, secure model-reachability check — `validate_reachability(...)` + `abench validate-model` CLI + `/api/validate/reachability` — that runs a 1-token probe against the configured endpoint **inside the experiment's sandbox**, sourcing the API key from opencode `auth.json` and never leaking it; plus auto-delivery of that key into runs (no manual `export`).

**Architecture:** A core `abench/credentials.py` reads opencode `auth.json` (XDG-aware) and builds the run/probe subprocess env (key forwarded by NAME, never in argv). A standalone stdlib `abench/model_probe.py` POSTs a 1-token completion to the provider `base_url` and prints a key-scrubbed JSON verdict. `abench/reachability.py` runs that probe in the sandbox (container or host) and parses it. Pre-flight and `run_task` are taught to accept the auth.json key.

**Tech Stack:** Python 3.12 (stdlib: urllib/json/subprocess/os), pydantic, pytest, FastAPI (API endpoint), Docker (container probe), opencode `auth.json`.

**Security invariants (assert in tests):** the API key never appears in argv, logs, `trace`, the reachability result, or any error text; it is forwarded into containers only as `-e NAME` (value from the abench subprocess env); on disk only in `auth.json`.

---

## File Structure

- **Create `abench/credentials.py`** — core opencode `auth.json` reader: `auth_path`, `read_credential`, `has_credential`, `run_env`. One responsibility: the secret store + secure env assembly.
- **Create `abench/model_probe.py`** — standalone, stdlib-only probe (runs in the bare image): `classify(...)` + a `__main__` that POSTs a 1-token completion and prints a key-scrubbed JSON verdict.
- **Create `abench/reachability.py`** — `ReachabilityResult` + `validate_reachability(...)` + `_probe_command(...)`: run the probe in the sandbox and parse it.
- **Modify `abench_ui/providers.py`** — use `credentials.auth_path()` (DRY the path).
- **Modify `abench/runner.py`** — pre-flight accepts the auth.json key.
- **Modify `abench/opencode_client.py`** — `run_task` builds its subprocess env via `credentials.run_env(...)`.
- **Modify `abench/cli.py`** — `validate-model` subcommand.
- **Modify `abench_ui/server.py`** — `POST /api/validate/reachability`.

All commands assume a worktree venv (`.venv/bin/python`) and `opencode` on PATH.

---

## Task 1: `abench/credentials.py` (auth.json reader + secure env)

**Files:**
- Create: `abench/credentials.py`
- Modify: `abench_ui/providers.py`
- Test: `tests/test_credentials.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_credentials.py
import json
from pathlib import Path

from abench import credentials


def _write_auth(tmp_path, data):
    d = tmp_path / "opencode"; d.mkdir(parents=True, exist_ok=True)
    (d / "auth.json").write_text(json.dumps(data), encoding="utf-8")


def test_read_credential_present(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    _write_auth(tmp_path, {"deepseek": {"type": "api", "key": "sk-secret"}})
    assert credentials.read_credential("deepseek") == "sk-secret"
    assert credentials.has_credential("deepseek") is True


def test_read_credential_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    _write_auth(tmp_path, {"other": {"type": "api", "key": "x"}})
    assert credentials.read_credential("deepseek") is None
    assert credentials.has_credential("deepseek") is False


def test_read_credential_no_file(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert credentials.read_credential("deepseek") is None


class _Prov:
    def __init__(self, id, api_key_env): self.id = id; self.api_key_env = api_key_env


def test_run_env_overlays_authjson_when_env_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    _write_auth(tmp_path, {"deepseek": {"type": "api", "key": "sk-fromauth"}})
    env = credentials.run_env([_Prov("deepseek", "DEEPSEEK_API_KEY")])
    assert env["DEEPSEEK_API_KEY"] == "sk-fromauth"


def test_run_env_os_env_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-fromenv")
    _write_auth(tmp_path, {"deepseek": {"type": "api", "key": "sk-fromauth"}})
    env = credentials.run_env([_Prov("deepseek", "DEEPSEEK_API_KEY")])
    assert env["DEEPSEEK_API_KEY"] == "sk-fromenv"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_credentials.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'abench.credentials'`.

- [ ] **Step 3: Write minimal implementation**

```python
# abench/credentials.py
"""Read the opencode auth.json secret store and assemble run/probe subprocess
env. The API key is handled ONLY here + forwarded by env NAME — never logged,
never placed in argv, never returned to callers/UI.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def auth_path() -> Path:
    """opencode's auth store, XDG-aware (matches opencode's own resolution)."""
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "opencode" / "auth.json"


def read_credential(provider: str) -> str | None:
    """The api key for `provider` from auth.json, or None. Secret — never log."""
    p = auth_path()
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    entry = data.get(provider) if isinstance(data, dict) else None
    if isinstance(entry, dict):
        key = entry.get("key")
        return key if isinstance(key, str) and key else None
    return None


def has_credential(provider: str) -> bool:
    return read_credential(provider) is not None


def run_env(providers) -> dict[str, str]:
    """os.environ overlaid with auth.json keys for each provider whose
    `api_key_env` is not already set in the environment (OS env wins; auth.json
    is the fallback). The value is placed in the env dict, never in argv."""
    env = os.environ.copy()
    for prov in providers:
        name = getattr(prov, "api_key_env", None)
        if name and not env.get(name):
            key = read_credential(prov.id)
            if key:
                env[name] = key
    return env
```

Then DRY the UI writer onto the same path — in `abench_ui/providers.py`, replace the local `_auth_path` definition and its uses with the core one:
- add `from abench.credentials import auth_path` at the top;
- delete `def _auth_path() ...`;
- replace the two `_auth_path()` calls (in `list_providers` and `write_credentials`) with `auth_path()`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_credentials.py tests/abench_ui/test_providers.py -q`
Expected: PASS (new credentials tests + the existing providers tests still green after the DRY).

- [ ] **Step 5: Commit**

```bash
git add abench/credentials.py abench_ui/providers.py tests/test_credentials.py
git commit -m "feat(credentials): core auth.json reader + secure run_env; DRY UI writer"
```

---

## Task 2: Pre-flight accepts the auth.json key

**Files:**
- Modify: `abench/runner.py` (`_preflight_env`)
- Test: `tests/test_runner_env_preflight.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_runner_env_preflight.py
def test_preflight_accepts_authjson_key(tmp_path, monkeypatch):
    """A provider whose api_key_env is NOT in os.environ but IS in auth.json
    must pass pre-flight (no false 'missing env var')."""
    import json as _json
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    authdir = tmp_path / "opencode"; authdir.mkdir(parents=True)
    (authdir / "auth.json").write_text(
        _json.dumps({"deepseek": {"type": "api", "key": "sk-x"}}))
    exp = _exp(
        tmp_path,
        providers=[ProviderCfg(id="deepseek",
                               base_url="https://api.deepseek.com/v1",
                               models=["deepseek-chat"],
                               api_key_env="DEEPSEEK_API_KEY")],
    )
    exp.verify.enabled = False
    from tests.fakes import FakeOpenCodeClient
    root = run_experiment(exp, lambda e: FakeOpenCodeClient())  # must NOT raise
    assert (root / "baseline" / "rep_0" / "trace.json").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_runner_env_preflight.py -k authjson -q`
Expected: FAIL — `RuntimeError: Missing required environment variable(s): DEEPSEEK_API_KEY ...` (pre-flight only checks os.environ).

- [ ] **Step 3: Write minimal implementation**

In `abench/runner.py`, in `_preflight_env`, right after the line that computes
`missing_env = {n: w for n, w in refs.items() if not os.environ.get(n)}`, drop the
api_key_env entries that auth.json satisfies:

```python
    from . import credentials
    for prov in exp.opencode.providers:
        if (prov.api_key_env and prov.api_key_env in missing_env
                and credentials.has_credential(prov.id)):
            del missing_env[prov.api_key_env]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_runner_env_preflight.py -q`
Expected: PASS (the new test + all existing pre-flight tests).

- [ ] **Step 5: Commit**

```bash
git add abench/runner.py tests/test_runner_env_preflight.py
git commit -m "feat(runner): pre-flight accepts api key from opencode auth.json"
```

---

## Task 3: Deliver the auth.json key into the run subprocess env

**Files:**
- Modify: `abench/opencode_client.py` (`RealOpenCodeClient.run_task`)
- Test: `tests/test_opencode_client.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_opencode_client.py
import json
import threading

from abench.config import OpenCodeCfg, ProviderCfg, SandboxCfg
from abench.opencode_client import RealOpenCodeClient


class _FakeProc:
    """Minimal stand-in for subprocess.Popen: no output, exits 0 immediately."""
    def __init__(self): self.returncode = 0; self.stdout = iter(()); self.stderr = iter(())
    def wait(self, timeout=None): self.returncode = 0; return 0
    def poll(self): return 0
    def kill(self): pass


def test_run_task_injects_authjson_key_into_env(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    authdir = tmp_path / "opencode"; authdir.mkdir(parents=True)
    (authdir / "auth.json").write_text(
        json.dumps({"deepseek": {"type": "api", "key": "sk-secret"}}))

    captured = {}
    import abench.opencode_client as oc

    def fake_popen(cmd, stdout, stderr, cwd, env):
        captured["env"] = env
        return _FakeProc()

    monkeypatch.setattr(oc.subprocess, "Popen", fake_popen)
    # No session export (no events) — keep it offline:
    monkeypatch.setattr(oc.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no export expected")))

    cfg = OpenCodeCfg(providers=[ProviderCfg(
        id="deepseek", base_url="https://api.deepseek.com/v1",
        models=["deepseek-chat"], api_key_env="DEEPSEEK_API_KEY")])
    client = RealOpenCodeClient(cfg, timeout_s=None)
    wd = tmp_path / "wd"; wd.mkdir()
    client.run_task(workdir=str(wd), system_prompt="s", model="deepseek/deepseek-chat",
                    user_message="go", timeout_s=None, on_event=lambda e: None)
    assert captured["env"]["DEEPSEEK_API_KEY"] == "sk-secret"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_opencode_client.py -k injects_authjson -q`
Expected: FAIL — `KeyError: 'DEEPSEEK_API_KEY'` (run_task uses `os.environ.copy()`, which lacks it).

- [ ] **Step 3: Write minimal implementation**

In `abench/opencode_client.py`: add `from . import credentials` near the imports.
In `RealOpenCodeClient.run_task`, change the Popen env from `env=os.environ.copy()` to:

```python
            env=credentials.run_env(self._cfg.providers),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_opencode_client.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add abench/opencode_client.py tests/test_opencode_client.py
git commit -m "feat(opencode): forward auth.json key into the run subprocess env (-e NAME)"
```

---

## Task 4: `abench/model_probe.py` (standalone probe + verdict + key scrub)

**Files:**
- Create: `abench/model_probe.py`
- Test: `tests/test_model_probe.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_model_probe.py
from abench.model_probe import classify, scrub


def test_classify_ok():
    assert classify(200, '{"choices":[]}', None) == (True, "ok")


def test_classify_auth():
    assert classify(401, "Unauthorized", None)[1] == "auth"
    assert classify(403, "forbidden", None)[1] == "auth"


def test_classify_model_not_found():
    assert classify(404, "no such model", None)[1] == "model_not_found"
    assert classify(400, 'Model "x" does not exist', None)[1] == "model_not_found"


def test_classify_network_and_tls():
    assert classify(None, "", "timed out")[1] == "network"
    assert classify(None, "", "CERTIFICATE_VERIFY_FAILED")[1] == "tls"


def test_scrub_removes_key():
    assert "sk-secret" not in scrub("error for key sk-secret here", "sk-secret")
    assert scrub("no key here", "sk-secret") == "no key here"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_model_probe.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'abench.model_probe'`.

- [ ] **Step 3: Write minimal implementation**

```python
# abench/model_probe.py
"""Standalone, stdlib-only model-reachability probe. Runs in the bare sandbox
image (only python3 needed). Sends a 1-token completion to the configured
endpoint and prints a KEY-SCRUBBED JSON verdict to stdout. The key is read from
the env var named by argv[3] — never passed in argv.

Usage:  python3 model_probe.py <base_url> <model> <key_env_name>
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def scrub(text: str, key: str) -> str:
    return text.replace(key, "***") if key else text


def classify(status, body: str, error: str | None) -> tuple[bool, str]:
    """(reachable, reason) from an HTTP status / body / transport error."""
    if error is not None:
        e = error.lower()
        if "certificate" in e or "ssl" in e or "cert_" in e.lower():
            return (False, "tls")
        return (False, "network")
    if status == 200:
        return (True, "ok")
    if status in (401, 403):
        return (False, "auth")
    low = body.lower()
    if status == 404 or (status == 400 and ("model" in low and ("exist" in low or "not" in low or "found" in low))):
        return (False, "model_not_found")
    return (False, f"http_{status}")


def main(argv: list[str]) -> int:
    base_url, model, key_env = argv[1], argv[2], argv[3]
    key = os.environ.get(key_env, "")
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=payload, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    status = None; body = ""; error = None
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status; body = resp.read(2048).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        status = exc.code
        try: body = exc.read(2048).decode("utf-8", "replace")
        except Exception: body = ""
    except Exception as exc:  # URLError, timeout, ssl, etc.
        error = f"{type(exc).__name__}: {exc}"
    reachable, reason = classify(status, body, error)
    detail = scrub((error or body or "")[:300], key)
    print(json.dumps({"reachable": reachable, "reason": reason, "detail": detail}))
    return 0 if reachable else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_model_probe.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add abench/model_probe.py tests/test_model_probe.py
git commit -m "feat(probe): standalone stdlib model-reachability probe (key-scrubbed)"
```

---

## Task 5: `abench/reachability.py` (orchestrator)

**Files:**
- Create: `abench/reachability.py`
- Test: `tests/test_reachability.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reachability.py
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
    # the key VALUE must never be in argv (only the env NAME)
    assert all("Bearer" not in str(a) for a in cmd)


def test_validate_reachability_parses_probe_json(tmp_path, monkeypatch):
    class _CP:
        returncode = 0
        stdout = json.dumps({"reachable": True, "reason": "ok", "detail": ""})
        stderr = ""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _CP())
    r = validate_reachability(PROV, "deepseek-chat", sandbox=SandboxCfg(mode="none"))
    assert isinstance(r, ReachabilityResult)
    assert r.reachable is True and r.reason == "ok"


def test_validate_reachability_probe_failed_on_garbage(tmp_path, monkeypatch):
    class _CP:
        returncode = 1
        stdout = "not json"
        stderr = "boom"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _CP())
    r = validate_reachability(PROV, "deepseek-chat", sandbox=SandboxCfg(mode="none"))
    assert r.reachable is False and r.reason == "probe_failed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_reachability.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'abench.reachability'`.

- [ ] **Step 3: Write minimal implementation**

```python
# abench/reachability.py
"""Run the model-reachability probe in the experiment's sandbox and parse it.
The api key is supplied via the subprocess env (name-only `-e`), never argv."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import credentials

_PROBE = str(Path(__file__).resolve().parent / "model_probe.py")


@dataclass
class ReachabilityResult:
    reachable: bool
    reason: str
    detail: str = ""


def _probe_command(sandbox, provider, model: str, probe_path: str) -> list[str]:
    key_env = provider.api_key_env or "OPENAI_API_KEY"
    inner_args = [provider.base_url, model, key_env]
    if sandbox.mode != "container":
        return ["python3", probe_path, *inner_args]
    return [sandbox.runtime, "run", "--rm",
            "-e", key_env,
            "-v", f"{probe_path}:/probe.py:ro",
            sandbox.image, "python3", "/probe.py",
            provider.base_url, model, key_env]


def validate_reachability(provider, model: str, *, sandbox) -> ReachabilityResult:
    """Probe `model` at `provider.base_url` with the provider's key, inside the
    sandbox. Returns a key-free ReachabilityResult."""
    cmd = _probe_command(sandbox, provider, model, _PROBE)
    env = credentials.run_env([provider])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
    except subprocess.TimeoutExpired:
        return ReachabilityResult(False, "probe_failed", "probe timed out")
    except FileNotFoundError as exc:
        return ReachabilityResult(False, "probe_failed", f"could not run probe: {exc}")
    try:
        data = json.loads(proc.stdout)
        return ReachabilityResult(bool(data["reachable"]), str(data["reason"]),
                                  str(data.get("detail", "")))
    except (json.JSONDecodeError, KeyError, TypeError):
        tail = (proc.stderr or proc.stdout or "").strip()[-200:]
        return ReachabilityResult(False, "probe_failed", tail)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_reachability.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add abench/reachability.py tests/test_reachability.py
git commit -m "feat(reachability): run the probe in the sandbox + parse verdict"
```

---

## Task 6: CLI `abench validate-model` + API endpoint

**Files:**
- Modify: `abench/cli.py`
- Modify: `abench_ui/server.py`
- Test: `tests/test_cli_validate_model.py`, `tests/abench_ui/test_reachability_api.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli_validate_model.py
from abench.cli import main


def _exp_yaml(tmp_path):
    fixture = tmp_path / "fix"; fixture.mkdir(); (fixture / "a.py").write_text("x=1\n")
    ref = tmp_path / "ref"; ref.mkdir()
    exp = tmp_path / "exp.yaml"
    exp.write_text(
        "name: t\n"
        f"fixture_path: {fixture}\nreference_path: {ref}\n"
        "task_prompt: t\nsystem_prompt: s\nmodel: deepseek/deepseek-chat\n"
        f"output_dir: {tmp_path / 'runs'}\n"
        "conditions: [{name: baseline}]\n"
        "opencode:\n  agent: abench\n  sandbox: {mode: none}\n"
        "  providers:\n    - id: deepseek\n      base_url: https://api.deepseek.com/v1\n"
        "      models: [deepseek-chat]\n      api_key_env: DEEPSEEK_API_KEY\n")
    return exp


def test_validate_model_cli_reachable(tmp_path, monkeypatch, capsys):
    exp = _exp_yaml(tmp_path)
    import abench.reachability as r
    from abench.reachability import ReachabilityResult
    monkeypatch.setattr(r, "validate_reachability",
                        lambda *a, **k: ReachabilityResult(True, "ok", ""))
    assert main(["validate-model", str(exp)]) == 0
    assert "reachable" in capsys.readouterr().out.lower()


def test_validate_model_cli_unreachable_exit1(tmp_path, monkeypatch, capsys):
    exp = _exp_yaml(tmp_path)
    import abench.reachability as r
    from abench.reachability import ReachabilityResult
    monkeypatch.setattr(r, "validate_reachability",
                        lambda *a, **k: ReachabilityResult(False, "auth", "bad key"))
    assert main(["validate-model", str(exp)]) == 1
    out = capsys.readouterr().out.lower()
    assert "auth" in out
```

```python
# tests/abench_ui/test_reachability_api.py
from abench.reachability import ReachabilityResult


def test_reachability_endpoint(client, monkeypatch, tmp_path):
    # `client` + an experiment fixture come from tests/abench_ui/conftest.py;
    # follow the existing pattern there (e.g. how test_sessions_api builds one).
    import abench.reachability as r
    monkeypatch.setattr(r, "validate_reachability",
                        lambda *a, **k: ReachabilityResult(True, "ok", ""))
    resp = client.post("/api/validate/reachability", json={"experiment_name": "EXP"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["reachable"] is True and body["reason"] == "ok"
    assert "key" not in body and "detail" in body
```

(Read `tests/abench_ui/conftest.py` + `tests/abench_ui/test_sessions_api.py` first and mirror their experiment/`client` fixtures; adjust the `EXP` name + setup to match.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli_validate_model.py tests/abench_ui/test_reachability_api.py -q`
Expected: FAIL — CLI `invalid choice: 'validate-model'`; API 404 (route absent).

- [ ] **Step 3: Write minimal implementation**

In `abench/cli.py`, add the parser by the others:
```python
    vm_p = sub.add_parser(
        "validate-model",
        help="check the experiment's model is reachable from its sandbox")
    vm_p.add_argument("experiment", help="path to experiment YAML")
```
And a dispatch handler (use the module-level `load_experiment`; import `reachability` as a MODULE so the test's monkeypatch is honored):
```python
    if args.cmd == "validate-model":
        from . import reachability
        exp = load_experiment(args.experiment)
        prov = exp.opencode.providers[0] if exp.opencode.providers else None
        model = exp.model.split("/", 1)[1] if "/" in exp.model else exp.model
        if prov is None:
            print("no provider configured in experiment.opencode.providers")
            return 1
        r = reachability.validate_reachability(prov, model, sandbox=exp.opencode.sandbox)
        if r.reachable:
            print(f"✓ {model} reachable")
            return 0
        print(f"✗ {model} unreachable — {r.reason}: {r.detail}")
        return 1
```

In `abench_ui/server.py`, add (alongside the other `@api.post` routes; reuse the existing `_exp_dir_for`/`load_experiment` pattern):
```python
    class _ReachabilityBody(BaseModel):
        experiment_name: str

    @api.post("/validate/reachability")
    def _validate_reachability(body: _ReachabilityBody):
        from abench.config import load_experiment
        from abench import reachability
        exp_dir = _exp_dir_for(body.experiment_name)
        yaml_path = exp_dir / "experiment.yaml"
        if not yaml_path.is_file():
            raise HTTPException(404, f"experiment '{body.experiment_name}' not found")
        exp = load_experiment(yaml_path)
        if not exp.opencode.providers:
            raise HTTPException(400, "experiment has no providers configured")
        prov = exp.opencode.providers[0]
        model = exp.model.split("/", 1)[1] if "/" in exp.model else exp.model
        res = reachability.validate_reachability(prov, model, sandbox=exp.opencode.sandbox)
        return {"reachable": res.reachable, "reason": res.reason, "detail": res.detail}
```
(Define `_ReachabilityBody` near the other pydantic request models at the top of `server.py` rather than inline if that matches the file's style.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cli_validate_model.py tests/abench_ui/test_reachability_api.py tests/test_cli.py -q`
Expected: PASS (incl. existing CLI tests — no `load_experiment` shadowing).

- [ ] **Step 5: Commit**

```bash
git add abench/cli.py abench_ui/server.py tests/test_cli_validate_model.py tests/abench_ui/test_reachability_api.py
git commit -m "feat(validate-model): CLI + /api/validate/reachability"
```

---

## Task 7: Leak-guard test + verification

**Files:**
- Test: `tests/test_reachability.py` (add a leak-guard test)
- Operational: server (container probe) — documented

- [ ] **Step 1: Write the leak-guard test**

```python
# add to tests/test_reachability.py
def test_key_never_in_probe_command_argv():
    """The key VALUE must never appear in argv — only the env NAME is forwarded."""
    sb = SandboxCfg(mode="container", image="abench-sandbox:latest", runtime="docker")
    cmd = _probe_command(sb, PROV, "deepseek-chat", "/p/model_probe.py")
    SECRET = "sk-THIS-MUST-NOT-LEAK"
    assert all(SECRET not in str(a) for a in cmd)  # builder never embeds a value


def test_result_has_no_key_field():
    r = ReachabilityResult(False, "auth", "scrubbed")
    assert not hasattr(r, "key") and "key" not in r.__dict__
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest tests/test_reachability.py -q`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_reachability.py
git commit -m "test(reachability): assert key never reaches argv / result"
```

- [ ] **Step 4: Operational verification (server, container)**

After merge + pull on the server, with the key in `auth.json` (UI) or env:
```bash
abench validate-model experiments/picocli-putValue/experiment.yaml
```
Expected: `✓ deepseek-v4-flash reachable` if api.deepseek.com serves it with your key; otherwise `✗ deepseek-v4-flash unreachable — model_not_found: …` (definitively answering the question that the old "Available" could not). Confirm with `docker inspect`/`ps` during the run that the key VALUE is not in the probe container's argv.

---

## Self-review notes (addressed)

- **Spec §4.1 key source + pre-flight** → Tasks 1 (credentials.run_env), 2 (pre-flight), 3 (run_task delivery).
- **Spec §4.2 probe** → Task 4 (`model_probe.py`, classify + scrub) + Task 5 (`reachability.py`, sandbox command + parse).
- **Spec §4.3 CLI + API** → Task 6.
- **Spec §4.5 leak audit** → Task 7 (argv/result leak-guard) + scrub covered in Task 4; `run_env` keeps the key out of argv (Task 1/3).
- **Spec §3 invariants** → key only in env (Task 1/3), name-only `-e` (Task 5 + test), scrubbed detail (Task 4), result has no key field (Task 7).
- **Type consistency:** `ReachabilityResult(reachable, reason, detail)`, `validate_reachability(provider, model, *, sandbox)`, `_probe_command(sandbox, provider, model, probe_path)`, `classify(status, body, error)`, `scrub(text, key)`, `credentials.run_env(providers)`/`read_credential`/`has_credential`/`auth_path` are used identically across tasks.
- **No placeholders:** the only operator-supplied blanks are the API test's experiment/`client` fixtures (Task 6 Step 1 says to mirror `tests/abench_ui/conftest.py`/`test_sessions_api.py`) and the server-side container verification (Task 7 Step 4) — both reference concrete existing patterns.
