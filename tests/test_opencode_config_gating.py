# tests/test_opencode_config_gating.py
from abench.config import OpenCodeCfg
from abench.opencode_client import build_opencode_config


def test_agent_tools_injected_when_provided():
    cfg = OpenCodeCfg(agent="abench")
    out = build_opencode_config(cfg, "m", "sys", agent_tools={"impact": False})
    assert out["agent"]["abench"]["tools"] == {"impact": False}


def test_no_tools_key_when_none():
    cfg = OpenCodeCfg(agent="abench")
    out = build_opencode_config(cfg, "m", "sys")
    assert "tools" not in out["agent"]["abench"]
