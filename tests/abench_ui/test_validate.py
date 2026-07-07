import subprocess
from unittest.mock import patch

import pytest

from abench_ui import validate as V
from abench_ui.validate import validate_model, ValidationResult, clear_caches


@pytest.fixture(autouse=True)
def _clear_caches():
    """Each test starts with empty TTL caches so monkeypatched CLIs take effect."""
    clear_caches()
    yield
    clear_caches()


def _fake_cli(args, **kwargs):
    """Pretend opencode CLI: providers list / models <p>."""
    text = " ".join(args) if isinstance(args, list) else args
    if "providers" in text:
        return subprocess.CompletedProcess(args, 0,
            stdout="opencode\nopenrouter\ndeepseek\n", stderr="")
    if "models" in text and "deepseek" in text:
        return subprocess.CompletedProcess(args, 0,
            stdout="deepseek/deepseek-chat\ndeepseek/deepseek-reasoner\n", stderr="")
    if "models" in text and "openrouter" in text:
        return subprocess.CompletedProcess(args, 0,
            stdout="openrouter/anthropic/claude-haiku-4.5\n", stderr="")
    return subprocess.CompletedProcess(args, 1, stdout="", stderr="unknown provider")


def test_validate_model_ok():
    with patch("abench_ui.validate.subprocess.run", side_effect=_fake_cli):
        result = validate_model("deepseek/deepseek-chat")
    assert result.status == "ok"
    assert result.provider == "deepseek"


def test_validate_model_no_credentials():
    def cli(args, **kw):
        text = " ".join(args)
        if "providers" in text:
            return subprocess.CompletedProcess(args, 0,
                stdout="opencode\n", stderr="")
        return _fake_cli(args, **kw)

    with patch("abench_ui.validate.subprocess.run", side_effect=cli):
        result = validate_model("deepseek/deepseek-chat")
    assert result.status == "no_credentials"
    assert result.provider == "deepseek"


def test_validate_model_not_in_catalog_with_suggestions():
    with patch("abench_ui.validate.subprocess.run", side_effect=_fake_cli):
        result = validate_model("deepseek/deepseek-chatt")  # typo
    assert result.status == "model_not_found"
    assert result.provider == "deepseek"
    assert any("deepseek-chat" in s for s in result.suggestions)


def test_validate_model_malformed():
    result = validate_model("nothing-here")
    assert result.status == "malformed"


def test_validate_model_unknown_provider():
    """Provider not in a successfully-fetched providers set → no_credentials."""
    with patch("abench_ui.validate.subprocess.run", side_effect=_fake_cli):
        result = validate_model("mars/some-model")
    assert result.status == "no_credentials"  # provider not in providers list


def test_validate_model_isolated_no_session_key():
    """Isolated: even though the SERVER has deepseek configured, a session with no
    key for it reports no_credentials — the chip reflects the visitor's own key."""
    with patch("abench_ui.validate.subprocess.run", side_effect=_fake_cli):
        result = validate_model("deepseek/deepseek-chat", session_providers=set())
    assert result.status == "no_credentials"
    assert result.provider == "deepseek"


def test_validate_model_isolated_with_session_key():
    """Isolated: provider present in this session → configured, so the catalog
    check proceeds to 'ok' instead of 'no_credentials'."""
    with patch("abench_ui.validate.subprocess.run", side_effect=_fake_cli):
        result = validate_model("deepseek/deepseek-chat",
                                session_providers={"deepseek"})
    assert result.status == "ok"
    assert result.provider == "deepseek"


# --- robustness of the low-level CLI wrappers ---------------------------------

def test_providers_returns_none_on_timeout():
    def boom(args, **kw):
        raise subprocess.TimeoutExpired(cmd=args, timeout=15)

    with patch("abench_ui.validate.subprocess.run", side_effect=boom):
        assert V._providers() is None


def test_providers_returns_none_on_missing_cli():
    def boom(args, **kw):
        raise FileNotFoundError("opencode not installed")

    with patch("abench_ui.validate.subprocess.run", side_effect=boom):
        assert V._providers() is None


def test_providers_returns_none_on_nonzero_returncode():
    def cli(args, **kw):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="boom")

    with patch("abench_ui.validate.subprocess.run", side_effect=cli):
        assert V._providers() is None


def test_providers_returns_set_on_success():
    with patch("abench_ui.validate.subprocess.run", side_effect=_fake_cli):
        provs = V._providers()
    assert provs == {"opencode", "openrouter", "deepseek"}


def test_models_returns_none_on_timeout():
    def boom(args, **kw):
        raise subprocess.TimeoutExpired(cmd=args, timeout=15)

    with patch("abench_ui.validate.subprocess.run", side_effect=boom):
        assert V._models("deepseek") is None


def test_models_returns_none_on_nonzero_returncode():
    def cli(args, **kw):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="boom")

    with patch("abench_ui.validate.subprocess.run", side_effect=cli):
        assert V._models("deepseek") is None


def test_models_returns_list_on_success():
    with patch("abench_ui.validate.subprocess.run", side_effect=_fake_cli):
        models = V._models("deepseek")
    assert models == ["deepseek/deepseek-chat", "deepseek/deepseek-reasoner"]


# --- unverified status (catalog/providers couldn't be fetched) ----------------

def test_validate_model_unverified_when_providers_none(monkeypatch):
    """Can't reach opencode to list providers → unverified, NOT a false negative."""
    monkeypatch.setattr(V, "_providers", lambda: None)
    result = validate_model("deepseek/deepseek-chat")
    assert result.status == "unverified"
    assert result.provider == "deepseek"


def test_validate_model_unverified_when_models_none(monkeypatch):
    """Provider configured but catalog couldn't be fetched → unverified."""
    monkeypatch.setattr(V, "_providers", lambda: {"deepseek"})
    monkeypatch.setattr(V, "_models", lambda p: None)
    result = validate_model("deepseek/deepseek-chat")
    assert result.status == "unverified"
    assert result.provider == "deepseek"


def test_validate_model_not_found_only_when_catalog_genuinely_lacks_it(monkeypatch):
    """model_not_found only when the catalog is a real (non-None) list missing it."""
    monkeypatch.setattr(V, "_providers", lambda: {"deepseek"})
    monkeypatch.setattr(V, "_models", lambda p: ["deepseek/deepseek-chat"])
    result = validate_model("deepseek/deepseek-nope")
    assert result.status == "model_not_found"
    assert result.provider == "deepseek"


def test_validate_model_no_credentials_when_provider_missing_from_nonnone_set(monkeypatch):
    monkeypatch.setattr(V, "_providers", lambda: {"openrouter"})
    result = validate_model("deepseek/deepseek-chat")
    assert result.status == "no_credentials"
    assert result.provider == "deepseek"


def test_validate_model_ok_via_monkeypatch(monkeypatch):
    monkeypatch.setattr(V, "_providers", lambda: {"deepseek"})
    monkeypatch.setattr(V, "_models", lambda p: ["deepseek/deepseek-chat"])
    result = validate_model("deepseek/deepseek-chat")
    assert result.status == "ok"


def test_list_model_catalog_tolerates_none(monkeypatch):
    """Catalog listing must not blow up when the CLI is unreachable."""
    monkeypatch.setattr(V, "_providers", lambda: None)
    assert V.list_model_catalog() == []
    monkeypatch.setattr(V, "_providers", lambda: {"deepseek"})
    monkeypatch.setattr(V, "_models", lambda p: None)
    assert V.list_model_catalog() == []
