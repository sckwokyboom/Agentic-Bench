"""Validate model availability without any chat-completion calls.

The check is ADVISORY: it never gates Save/Run. It must also be robust to the
`opencode` CLI being missing, slow, or unable to reach the model registry
(proxy/network blocked is common in users' envs) — in those cases we report
`unverified` ("couldn't determine") instead of a misleading `model_not_found`.

Sequence:
    1. `opencode providers list` (TTL 30s) → set of configured providers, or
       None if the CLI couldn't be reached.
    2. providers is None                  → status=unverified.
    3. provider not configured            → status=no_credentials.
    4. `opencode models <provider>` (TTL 5min) → catalog, or None on failure.
    5. catalog is None                    → status=unverified.
    6. model id in catalog                → status=ok.
    7. else                               → status=model_not_found + difflib.
"""
from __future__ import annotations

import difflib
import subprocess
from dataclasses import dataclass, field
from typing import Literal

from cachetools import TTLCache, cached

Status = Literal["ok", "no_credentials", "model_not_found", "malformed", "unverified"]


@dataclass
class ValidationResult:
    status: Status
    provider: str | None = None
    suggestions: list[str] = field(default_factory=list)


_PROVIDERS_CACHE: TTLCache = TTLCache(maxsize=1, ttl=30)
_MODELS_CACHE: TTLCache = TTLCache(maxsize=16, ttl=300)


def clear_caches() -> None:
    """Drop the providers + models TTL caches so the next validate() re-queries
    the opencode CLI. Called right after a credential write so a freshly-added
    key takes effect immediately instead of after the TTL expires."""
    _PROVIDERS_CACHE.clear()
    _MODELS_CACHE.clear()


@cached(_PROVIDERS_CACHE)
def _providers() -> set[str] | None:
    """Set of configured providers, or None if the CLI couldn't be queried
    (missing binary, timeout, OS error, or a non-zero exit). None means
    "couldn't determine" — distinct from an empty set (genuinely none)."""
    try:
        result = subprocess.run(
            ["opencode", "providers", "list"],
            capture_output=True, text=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
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
def _models(provider: str) -> list[str] | None:
    """Model ids for a provider, or None if the catalog couldn't be fetched
    (missing binary, timeout, OS error, or non-zero exit). None means
    "couldn't determine" — distinct from an empty list."""
    try:
        result = subprocess.run(
            ["opencode", "models", provider],
            capture_output=True, text=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def list_model_catalog() -> list[dict]:
    """[{provider, id}] for every model of every configured provider (cached).

    Tolerant of an unreachable CLI: Nones from `_providers`/`_models` are
    treated as empty so this never raises."""
    out: list[dict] = []
    for p in sorted(_providers() or set()):
        for m in (_models(p) or []):
            out.append({"provider": p, "id": m})
    return out


def validate_model(model: str, *, session_providers=None) -> ValidationResult:
    """When ``session_providers`` is given (exposed/isolated mode), a provider
    counts as configured iff THIS visitor's session has a key for it — not the
    server's global opencode config — so the 'no key' chip reflects the visitor's
    own session key."""
    if "/" not in model:
        return ValidationResult(status="malformed")
    provider, _ = model.split("/", 1)
    provider = provider.strip().lower()
    if not provider:
        return ValidationResult(status="malformed")

    if session_providers is not None:
        # Isolated mode: "configured" = this session provided a key for it.
        if provider not in session_providers:
            return ValidationResult(status="no_credentials", provider=provider)
    else:
        provs = _providers()
        if provs is None:
            # Couldn't reach opencode to list providers — advisory, don't scare.
            return ValidationResult(status="unverified", provider=provider)
        if provider not in provs:
            return ValidationResult(status="no_credentials", provider=provider)

    catalog = _models(provider)
    if catalog is None:
        # Provider is configured but the catalog couldn't be fetched.
        return ValidationResult(status="unverified", provider=provider)
    if model in catalog:
        return ValidationResult(status="ok", provider=provider)

    # close-match suggestions on the *full* id — only meaningful now that the
    # catalog was genuinely fetched.
    sugg = difflib.get_close_matches(model, catalog, n=3, cutoff=0.6)
    return ValidationResult(
        status="model_not_found", provider=provider, suggestions=sugg,
    )
