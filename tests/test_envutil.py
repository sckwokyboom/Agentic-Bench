import pytest
from abench.envutil import expand_env_refs

def test_expands_env_ref(monkeypatch):
    monkeypatch.setenv("GT_HOME", "/opt/gt")
    assert expand_env_refs("{env:GT_HOME}:/mnt:ro") == "/opt/gt:/mnt:ro"

def test_plain_string_untouched():
    assert expand_env_refs("/a/b:/c") == "/a/b:/c"

def test_missing_env_raises(monkeypatch):
    monkeypatch.delenv("NOPE_VAR", raising=False)
    with pytest.raises(ValueError, match="NOPE_VAR"):
        expand_env_refs("{env:NOPE_VAR}/x")
