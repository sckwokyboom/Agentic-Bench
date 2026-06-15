# tests/test_config_tools.py
from abench.config import Condition, OpenCodeCfg


def test_condition_tools_defaults_empty():
    assert Condition(name="baseline").tools == []


def test_condition_tools_listed():
    c = Condition(name="aug", tools=["impact"])
    assert c.tools == ["impact"]


def test_opencode_tools_lib_default_none():
    assert OpenCodeCfg().tools_lib is None
