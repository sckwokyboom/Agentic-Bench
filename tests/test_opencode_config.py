import json

from abench.config import OpenCodeCfg, ProviderCfg
from abench.opencode_client import build_opencode_config


def test_default_small_model_falls_back_to_main_model():
    """Default small_model must be the run's MAIN model — NOT an opencode-native
    gateway — so the bench uses the same provider the operator's interactive
    opencode reaches (a corporate proxy may forbid the opencode gateway even
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
