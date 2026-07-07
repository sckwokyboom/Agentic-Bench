from fastapi.testclient import TestClient

from abench_ui.server import create_app


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
