from fastapi.testclient import TestClient

from abench_ui import server as server_mod
from abench_ui.server import create_app


_EXP_YAML = """\
name: exp
fixture_path: ./stripped
reference_path: ./original
task_prompt: do it
system_prompt: sys
model: deepseek/deepseek-chat
output_dir: ./runs
verify: {enabled: false}
opencode:
  providers:
    - id: deepseek
      base_url: https://api.deepseek.com/v1
      models: [deepseek-chat]
      api_key_env: DEEPSEEK_API_KEY
conditions:
  - {name: baseline}
target_file: a.java
target_methods: [x]
"""


def _write_exp(tmp_path):
    d = tmp_path / "exp"
    (d / "stripped").mkdir(parents=True)
    (d / "original").mkdir(parents=True)
    (d / "stripped" / "a.java").write_text("class A {}")
    (d / "original" / "a.java").write_text("class A {}")
    (d / "experiment.yaml").write_text(_EXP_YAML)


def test_isolated_run_threads_the_session_key_into_the_client(tmp_path, monkeypatch):
    """The whole point of --expose: the run must use the visitor's session key
    (by cookie), not a placeholder. Reproduces the 'no API key' path end to end."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    _write_exp(tmp_path)
    app = create_app(experiments_dir=tmp_path, isolated=True)

    captured = {}

    class _SpyClient:
        def __init__(self, cfg, timeout_s=None, *, session_keys=None, isolated=False):
            captured["session_keys"] = session_keys

    class _FakeSession:
        def __init__(self, *, id, experiment, client_factory, publish,
                     batch_id=None, isolated=False):
            client_factory(experiment)      # trigger client construction now
            self.id = id

        def start(self):
            pass

    monkeypatch.setattr(server_mod, "RealOpenCodeClient", _SpyClient)
    monkeypatch.setattr(server_mod, "RunSession", _FakeSession)

    client = TestClient(app)
    client.post("/api/providers/deepseek/credentials", json={"api_key": "sk-visitor"})
    r = client.post("/api/runs", json={"experiment_name": "exp"})
    assert r.status_code == 200
    assert captured["session_keys"] == {"deepseek": "sk-visitor"}


def test_preflight_no_key_warning_when_isolated(tmp_path, monkeypatch):
    """The scary 'no API key' WARN must NOT fire in isolated mode — the key is
    provided per-session, not via env/auth.json. On localhost it still warns."""
    from abench import runner as R
    from abench.config import load_experiment
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))     # no auth.json entry
    _write_exp(tmp_path)
    exp = load_experiment(tmp_path / "exp" / "experiment.yaml")

    logs: list[str] = []
    monkeypatch.setattr(R, "_log", logs.append)
    R._preflight_env(exp, isolated=True)
    assert not any("has no API key" in m for m in logs)    # isolated → no scare
    logs.clear()
    R._preflight_env(exp, isolated=False)
    assert any("has no API key" in m for m in logs)        # localhost → still warns


def test_isolated_credentials_go_to_session_store_not_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))   # any disk write would land here
    app = create_app(experiments_dir=tmp_path, isolated=True)
    client = TestClient(app)

    r = client.post("/api/providers/deepseek/credentials", json={"api_key": "sk-visitor"})
    assert r.status_code == 200

    tok = client.cookies.get("abench_session")
    assert tok
    store = app.state.abench["session_store"]
    assert store.get(tok, "deepseek") == "sk-visitor"     # in memory, THIS session

    from abench.credentials import auth_path
    assert not auth_path().is_file()                       # NOT persisted to disk


def test_isolated_sessions_do_not_share_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    app = create_app(experiments_dir=tmp_path, isolated=True)
    c1, c2 = TestClient(app), TestClient(app)

    c1.post("/api/providers/deepseek/credentials", json={"api_key": "sk-1"})
    c2.post("/api/providers/deepseek/credentials", json={"api_key": "sk-2"})

    store = app.state.abench["session_store"]
    t1, t2 = c1.cookies.get("abench_session"), c2.cookies.get("abench_session")
    assert t1 and t2 and t1 != t2
    assert store.get(t1, "deepseek") == "sk-1"
    assert store.get(t2, "deepseek") == "sk-2"


def test_runtime_mode_reports_isolated(tmp_path):
    assert TestClient(create_app(experiments_dir=tmp_path, isolated=True)) \
        .get("/api/runtime-mode").json() == {"isolated": True}
    assert TestClient(create_app(experiments_dir=tmp_path, isolated=False)) \
        .get("/api/runtime-mode").json() == {"isolated": False}


def test_non_isolated_credentials_write_to_disk(tmp_path, monkeypatch):
    """Default (localhost) mode is unchanged: keys go to the shared auth.json."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    app = create_app(experiments_dir=tmp_path, isolated=False)
    r = TestClient(app).post("/api/providers/deepseek/credentials", json={"api_key": "sk-disk"})
    assert r.status_code == 200

    from abench.credentials import read_credential
    assert read_credential("deepseek") == "sk-disk"        # written to disk, as before
    assert app.state.abench["session_store"].get("anytok", "deepseek") is None


def test_isolated_validate_model_reflects_the_session_key(tmp_path, monkeypatch):
    """/api/validate/model 'no key' tracks THIS session, not the server config:
    no_credentials until this visitor adds a key, then it clears."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    app = create_app(experiments_dir=tmp_path, isolated=True)
    client = TestClient(app)

    r = client.post("/api/validate/model", json={"model": "deepseek/deepseek-chat"})
    assert r.json()["status"] == "no_credentials"          # session has no key yet

    client.post("/api/providers/deepseek/credentials", json={"api_key": "sk-visitor"})
    r2 = client.post("/api/validate/model", json={"model": "deepseek/deepseek-chat"})
    assert r2.json()["status"] != "no_credentials"         # session key now recognised
