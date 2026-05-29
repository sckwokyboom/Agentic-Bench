"""Validate model availability without any chat-completion calls.

Sequence:
    1. `opencode providers list` (TTL 30s) → set of configured providers.
    2. If provider not configured → status=no_credentials, return.
    3. `opencode models <provider>` (TTL 5min) → catalog.
    4. If model id in catalog → status=ok.
    5. Else → status=model_not_found + difflib suggestions.
"""
from __future__ import annotations

import difflib
import subprocess
from dataclasses import dataclass, field
from typing import Literal

from cachetools import TTLCache, cached

Status = Literal["ok", "no_credentials", "model_not_found", "malformed"]


@dataclass
class ValidationResult:
    status: Status
    provider: str | None = None
    suggestions: list[str] = field(default_factory=list)


_PROVIDERS_CACHE: TTLCache = TTLCache(maxsize=1, ttl=30)
_MODELS_CACHE: TTLCache = TTLCache(maxsize=16, ttl=300)


@cached(_PROVIDERS_CACHE)
def _providers() -> set[str]:
    result = subprocess.run(
        ["opencode", "providers", "list"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        return set()
    out: set[str] = set()
    for raw in result.stdout.splitlines():
        line = raw.strip()
        if not line or line.startswith("┌") or line.startswith("│") or line.startswith("└"):
            continue
        # accept either bare names or markers like "●  OpenAI"
        token = line.lstrip("● ").split()[0].lower()
        if token:
            out.add(token)
    return out


@cached(_MODELS_CACHE)
def _models(provider: str) -> list[str]:
    result = subprocess.run(
        ["opencode", "models", provider],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def validate_model(model: str) -> ValidationResult:
    if "/" not in model:
        return ValidationResult(status="malformed")
    provider, _ = model.split("/", 1)
    provider = provider.strip().lower()
    if not provider:
        return ValidationResult(status="malformed")

    if provider not in _providers():
        return ValidationResult(status="no_credentials", provider=provider)

    catalog = _models(provider)
    if model in catalog:
        return ValidationResult(status="ok", provider=provider)

    # close-match suggestions on the *full* id
    sugg = difflib.get_close_matches(model, catalog, n=3, cutoff=0.6)
    return ValidationResult(
        status="model_not_found", provider=provider, suggestions=sugg,
    )
