import subprocess
from unittest.mock import patch

import pytest

from abench_ui.validate import validate_model, ValidationResult


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
    """`opencode models <p>` exit non-zero with unknown provider."""
    with patch("abench_ui.validate.subprocess.run", side_effect=_fake_cli):
        result = validate_model("mars/some-model")
    assert result.status == "no_credentials"  # provider not in providers list
