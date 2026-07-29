import json

import pytest

from abench.config import OpenCodeCfg, ProviderCfg
from abench.opencode_client import build_opencode_config


def test_default_small_model_falls_back_to_main_model():
    """Default small_model must be the run's MAIN model — NOT an opencode-native
    gateway — so the bench uses the same provider the operator's interactive
    opencode reaches (a restrictive network may forbid the opencode gateway even
    when the main model works)."""
    cfg = OpenCodeCfg()
    config = build_opencode_config(cfg, "openrouter/x", "sys")

    assert "provider" not in config
    assert config["small_model"] == "openrouter/x"   # == main model, not opencode/*
    assert config["model"] == "openrouter/x"
    assert config["$schema"] == "https://opencode.ai/config.json"
    agent_block = config["agent"][cfg.agent]
    assert agent_block == {"prompt": "sys", "model": "openrouter/x"}


def test_small_model_override_is_respected():
    cfg = OpenCodeCfg(
        small_model="cheap/helper",
        providers=[
            ProviderCfg(
                id="kimi",
                base_url="https://h/v1",
                models=["kimi-k2.6"],
                api_key_env="KIMI_API_KEY",
            )
        ],
    )
    config = build_opencode_config(cfg, "kimi/kimi-k2.6", "sys")

    assert config["small_model"] == "cheap/helper"
    assert config["provider"]["kimi"] == {
        "npm": "@ai-sdk/openai-compatible",
        "models": {"kimi-k2.6": {}},
        "options": {
            "baseURL": "https://h/v1",
            "apiKey": "{env:KIMI_API_KEY}",
        },
    }


def test_provider_without_api_key_env_omits_apikey_and_carries_no_secret():
    cfg = OpenCodeCfg(
        providers=[
            ProviderCfg(
                id="kimi",
                base_url="https://h/v1",
                models=["kimi-k2.6"],
            )
        ],
    )
    config = build_opencode_config(cfg, "kimi/kimi-k2.6", "sys")

    block = config["provider"]["kimi"]
    assert block["options"]["baseURL"] == "https://h/v1"
    assert "apiKey" not in block["options"]

    # SECURITY: there must be no field on ProviderCfg that could carry a raw
    # secret, so the serialized config cannot leak one into opencode.json.
    prov_fields = set(ProviderCfg.model_fields)
    assert "api_key" not in prov_fields
    assert "key" not in prov_fields
    assert "apiKey" not in prov_fields
    assert "secret" not in prov_fields

    serialized = json.dumps(config)
    # No raw secret value is present; only the env-ref form is allowed.
    assert "apiKey" not in serialized


def test_display_name_is_emitted_when_set():
    cfg = OpenCodeCfg(
        providers=[
            ProviderCfg(
                id="kimi",
                base_url="https://h/v1",
                models=["kimi-k2.6"],
                name="Kimi",
            )
        ],
    )
    config = build_opencode_config(cfg, "kimi/kimi-k2.6", "sys")
    assert config["provider"]["kimi"]["name"] == "Kimi"


# ── Sandbox / build_run_command ──────────────────────────────────────────────

from abench.config import SandboxCfg
from abench.opencode_client import build_run_command, _env_refs_in_config


def test_sandbox_defaults_to_none():
    assert OpenCodeCfg().sandbox.mode == "none"


def test_idle_timeout_default_is_fifteen_minutes():
    # The no-output watchdog: kills a hung run after this long with NO model output
    # so an unattended experiment never wedges forever (even with no overall timeout).
    # Raised 600 -> 900 when the watchdog was re-keyed to model progress only: it must
    # exceed the longest legitimate gap between tokens, or it drops healthy runs.
    assert OpenCodeCfg().idle_timeout_s == 900


def test_build_run_command_none_is_direct_host_invocation():
    cfg = OpenCodeCfg()
    cmd = build_run_command(cfg, workdir="/host/wd", model="m", user_message="do it",
                            config_data={})
    assert cmd[0] == "opencode" and cmd[1] == "run"
    assert "--dir" in cmd and cmd[cmd.index("--dir") + 1] == "/host/wd"
    assert "--dangerously-skip-permissions" in cmd
    assert cmd[-1] == "do it"
    # No container runtime is involved.
    assert "docker" not in cmd and "podman" not in cmd


def test_build_run_command_rejects_oversize_user_message():
    """A prompt over the single-argv limit must fail with a CLEAR, actionable
    error — not the cryptic OSError E2BIG ('Argument list too long') that
    opencode/docker would otherwise raise on spawn."""
    cfg = OpenCodeCfg()
    with pytest.raises(ValueError, match="Argument list too long"):
        build_run_command(cfg, workdir="/wd", model="m",
                          user_message="X" * 200_000, config_data={})


def test_build_run_command_container_wraps_and_isolates():
    cfg = OpenCodeCfg(sandbox=SandboxCfg(
        mode="container", runtime="podman", image="img:1",
        network="none", cache_mounts=["/h/.gradle:/root/.gradle:ro"]))
    config_data = {"provider": {"p": {"options": {"apiKey": "{env:DEEPSEEK_KEY}"}}}}
    cmd = build_run_command(cfg, workdir="/host/wd", model="m",
                            user_message="go", config_data=config_data)

    assert cmd[:3] == ["podman", "run", "--rm"]
    # ONLY the run workdir is mounted at the container path; --dir points there.
    assert "-v" in cmd and "/host/wd:/work" in cmd
    assert cmd[cmd.index("--dir") + 1] == "/work"
    # egress policy + cache mount + image
    assert "--network" in cmd and cmd[cmd.index("--network") + 1] == "none"
    assert "/h/.gradle:/root/.gradle:ro" in cmd
    assert "img:1" in cmd
    # the provider key env is forwarded BY NAME (never the value)
    assert "-e" in cmd and "DEEPSEEK_KEY" in cmd
    # opencode itself still runs inside, skip-permissions intact (container is the
    # real boundary).
    assert "opencode" in cmd and "--dangerously-skip-permissions" in cmd
    assert cmd[-1] == "go"


def test_env_refs_are_collected_and_deduped():
    cfg = {"a": "{env:KEY_A}", "b": ["x", "{env:KEY_B}"], "c": "{env:KEY_A}"}
    assert _env_refs_in_config(cfg) == ["KEY_A", "KEY_B"]


def test_container_forwards_explicit_env_passthrough_too():
    cfg = OpenCodeCfg(sandbox=SandboxCfg(
        mode="container", env_passthrough=["EXTRA_ENV"]))
    cmd = build_run_command(cfg, workdir="/wd", model="m", user_message="x",
                            config_data={})
    assert "EXTRA_ENV" in cmd


def test_cache_mounts_expand_env_refs(monkeypatch):
    """cache_mounts with {env:NAME} references must be expanded before
    passing to the docker/podman -v flag. The expanded path must appear in
    argv; the raw {env:...} form must not."""
    monkeypatch.setenv("GT_HOME", "/x")
    cfg = OpenCodeCfg(sandbox=SandboxCfg(
        mode="container", cache_mounts=["{env:GT_HOME}:/opt/gt:ro"]))
    cmd = build_run_command(cfg, workdir="/wd", model="m", user_message="x",
                            config_data={})

    # The expanded value must be in argv
    assert "/x:/opt/gt:ro" in cmd
    # The raw {env:...} form must NOT be in argv
    assert "{env:GT_HOME}:/opt/gt:ro" not in cmd


def test_temperature_set_on_agent_block_when_provided():
    cfg = OpenCodeCfg()
    config = build_opencode_config(cfg, "openrouter/x", "sys", temperature=0.7)
    assert config["agent"][cfg.agent]["temperature"] == 0.7


def test_temperature_omitted_when_none_keeps_output_unchanged():
    cfg = OpenCodeCfg()
    config = build_opencode_config(cfg, "openrouter/x", "sys", temperature=None)
    assert "temperature" not in config["agent"][cfg.agent]
    assert config == build_opencode_config(cfg, "openrouter/x", "sys")
