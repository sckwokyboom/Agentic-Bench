# tests/test_runner_env_preflight.py
"""Fail-fast pre-flight: every {env:NAME} the run needs on the HOST is checked
BEFORE any slow work (sandbox image build, baseline verify) or the agent runs,
so a missing OS env var produces one clear up-front error listing them all —
instead of a cryptic ValueError deep in the first run, minutes later."""
import pytest

from abench.config import (
    Condition,
    Experiment,
    OpenCodeCfg,
    ProviderCfg,
    SandboxCfg,
)
from abench.runner import _preflight_env, _required_env_refs, run_experiment


def _exp(tmp_path, *, sandbox=None, providers=None, overlay_env=None):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "a.py").write_text("x = 1\n")
    reference = tmp_path / "reference"
    reference.mkdir()
    return Experiment(
        name="exp",
        fixture_path=fixture,
        reference_path=reference,
        task_prompt="t",
        system_prompt="s",
        model="deepseek/deepseek-chat",
        output_dir=tmp_path / "runs",
        repetitions=1,
        conditions=[Condition(name="baseline", augmentation=None)],
        opencode=OpenCodeCfg(
            sandbox=sandbox or SandboxCfg(),
            providers=providers or [],
        ),
        overlay_env=overlay_env or {},
    )


def test_required_env_refs_collects_all_sources(tmp_path):
    """cache_mounts (container only), overlay_env values, and a provider's
    api_key_env are all reported, each annotated with where it came from."""
    exp = _exp(
        tmp_path,
        sandbox=SandboxCfg(
            mode="container",
            cache_mounts=["{env:GRAPH_TIPPER_HOME}:/opt/graph-tipper:ro"],
        ),
        providers=[ProviderCfg(
            id="deepseek",
            base_url="https://api.deepseek.com/v1",
            models=["deepseek-chat"],
            api_key_env="DEEPSEEK_API_KEY",
        )],
        overlay_env={"X": "{env:SOME_HOST_PATH}"},
    )
    refs = _required_env_refs(exp)
    assert set(refs) == {"GRAPH_TIPPER_HOME", "DEEPSEEK_API_KEY", "SOME_HOST_PATH"}
    assert any("cache_mounts" in w for w in refs["GRAPH_TIPPER_HOME"])
    assert any("api key" in w for w in refs["DEEPSEEK_API_KEY"])
    assert any("overlay_env" in w for w in refs["SOME_HOST_PATH"])


def test_cache_mounts_only_required_in_container_mode(tmp_path):
    """In sandbox mode 'none' the bind mounts are never used, so their
    {env:} refs are not required on the host."""
    exp = _exp(
        tmp_path,
        sandbox=SandboxCfg(
            mode="none",
            cache_mounts=["{env:GRAPH_TIPPER_HOME}:/opt/graph-tipper:ro"],
        ),
    )
    assert "GRAPH_TIPPER_HOME" not in _required_env_refs(exp)


def test_run_experiment_fails_fast_on_missing_env(tmp_path, monkeypatch):
    """A GENUINELY-required host var — a container cache_mount {env:} — that is
    unset makes run_experiment raise a clear error BEFORE the client is ever
    constructed. (Provider API keys are OPTIONAL and must NOT block — see
    test_provider_api_key_is_optional_in_preflight.)"""
    monkeypatch.delenv("CACHE_HOST_DIR", raising=False)
    exp = _exp(
        tmp_path,
        sandbox=SandboxCfg(
            mode="container",
            cache_mounts=["{env:CACHE_HOST_DIR}:/cache:ro"],
        ),
    )

    def _factory(_e):  # must never be reached
        raise AssertionError("client built despite missing required env var")

    with pytest.raises(RuntimeError) as ei:
        run_experiment(exp, _factory)
    msg = str(ei.value)
    assert "CACHE_HOST_DIR" in msg
    # The message must orient the user: these are OS env vars, not a UI field.
    assert "environment variable" in msg.lower()


def test_provider_api_key_is_optional_in_preflight(tmp_path, monkeypatch):
    """A no-auth custom endpoint — a provider with api_key_env but NO key in the
    OS env OR auth.json — must NOT be blocked by the pre-flight. The provider key
    is OPTIONAL (run_env supplies a placeholder; a personal endpoint may need no
    auth). Genuinely-required vars (cache_mounts/overlay_env) still block."""
    monkeypatch.delenv("LOCAL_API_KEY", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))   # no auth.json entry
    exp = _exp(tmp_path, providers=[ProviderCfg(
        id="local",
        base_url="http://localhost:8080/v1",
        models=["local-model"],
        api_key_env="LOCAL_API_KEY",
    )])
    _preflight_env(exp)   # must NOT raise about the (optional) provider key


def test_preflight_accepts_authjson_key(tmp_path, monkeypatch):
    """A provider whose api_key_env is NOT in os.environ but IS in auth.json
    must pass pre-flight (no false 'missing env var')."""
    import json as _json
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    authdir = tmp_path / "opencode"
    authdir.mkdir(parents=True)
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


def test_run_experiment_proceeds_when_env_present(tmp_path, monkeypatch):
    """With the referenced var set, the pre-flight passes and the run executes."""
    from tests.fakes import FakeOpenCodeClient

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    exp = _exp(
        tmp_path,
        providers=[ProviderCfg(
            id="deepseek",
            base_url="https://api.deepseek.com/v1",
            models=["deepseek-chat"],
            api_key_env="DEEPSEEK_API_KEY",
        )],
    )
    exp.verify.enabled = False  # keep the test hermetic (no gradle/pytest)
    root = run_experiment(exp, lambda e: FakeOpenCodeClient())
    assert (root / "baseline" / "rep_0" / "trace.json").exists()


def test_preflight_reports_missing_lib(tmp_path, monkeypatch):
    monkeypatch.setenv("ABENCH_LOCAL_CONFIG", str(tmp_path / "nope.json"))
    exp = _exp(
        tmp_path,
        sandbox=SandboxCfg(
            mode="container",
            cache_mounts=["{lib:graph-tipper}:/opt/graph-tipper:ro"]),
    )

    def _factory(_e):
        raise AssertionError("client built despite missing library path")

    with pytest.raises(RuntimeError) as ei:
        run_experiment(exp, _factory)
    assert "graph-tipper" in str(ei.value)


def test_preflight_reports_unregistered_tools_lib(tmp_path, monkeypatch):
    """tools_lib naming a library absent from the registry must fail fast."""
    monkeypatch.setenv("ABENCH_LOCAL_CONFIG", str(tmp_path / "none.json"))
    exp = _exp(tmp_path)
    exp.opencode.tools_lib = "graph-tipper"  # set but never registered
    def _factory(_e):
        raise AssertionError("client built despite unregistered tools_lib")
    with pytest.raises(RuntimeError) as ei:
        run_experiment(exp, _factory)
    assert "graph-tipper" in str(ei.value)
