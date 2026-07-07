from abench_ui.session_creds import SessionCredentialStore


def test_set_get_roundtrip():
    s = SessionCredentialStore()
    s.set("tok1", "deepseek", "sk-a")
    assert s.get("tok1", "deepseek") == "sk-a"


def test_tokens_are_isolated():
    """The whole point: one visitor's key is invisible to another session's token."""
    s = SessionCredentialStore()
    s.set("tokA", "deepseek", "sk-A")
    s.set("tokB", "deepseek", "sk-B")
    assert s.get("tokA", "deepseek") == "sk-A"
    assert s.get("tokB", "deepseek") == "sk-B"
    assert s.get("tokC", "deepseek") is None


def test_keys_for_returns_a_copy():
    s = SessionCredentialStore()
    s.set("t", "deepseek", "sk-a")
    snapshot = s.keys_for("t")
    assert snapshot == {"deepseek": "sk-a"}
    snapshot["deepseek"] = "mutated"          # mutating the copy must not touch the store
    assert s.get("t", "deepseek") == "sk-a"
    assert s.keys_for("unknown") == {}


def test_has_any_and_clear():
    s = SessionCredentialStore()
    assert s.has_any("t") is False
    s.set("t", "deepseek", "sk-a")
    assert s.has_any("t") is True
    s.clear("t")
    assert s.has_any("t") is False
    assert s.get("t", "deepseek") is None


def test_new_token_is_unique_and_opaque():
    toks = {SessionCredentialStore.new_token() for _ in range(100)}
    assert len(toks) == 100
    assert all(len(t) >= 32 for t in toks)
