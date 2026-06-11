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
from abench.runner import _required_env_refs, run_experiment


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
    """A provider whose api_key_env is unset makes run_experiment raise a clear
    error BEFORE the client is ever constructed/called."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    exp = _exp(
        tmp_path,
        providers=[ProviderCfg(
            id="deepseek",
            base_url="https://api.deepseek.com/v1",
            models=["deepseek-chat"],
            api_key_env="DEEPSEEK_API_KEY",
        )],
    )

    def _factory(_e):  # must never be reached
        raise AssertionError("client built despite missing env var")

    with pytest.raises(RuntimeError) as ei:
        run_experiment(exp, _factory)
    msg = str(ei.value)
    assert "DEEPSEEK_API_KEY" in msg
    # The message must orient the user: these are OS env vars, not a UI field.
    assert "environment variable" in msg.lower()


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
