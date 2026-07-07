"""In-memory, per-session API-key store for the exposed (LAN) Web UI.

Keys live ONLY here — never on disk, never in the shared opencode ``auth.json`` —
keyed by an opaque session token, so LAN visitors never share or overwrite each
other's keys. Nothing is persisted: the store is empty again on process restart.
Values are secrets: never log them, never return them to a client.
"""
from __future__ import annotations

import secrets
import threading


class SessionCredentialStore:
    """Thread-safe ``{token: {provider: api_key}}``."""

    def __init__(self) -> None:
        self._by_token: dict[str, dict[str, str]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def new_token() -> str:
        """A fresh, unguessable session token (opaque, URL-safe)."""
        return secrets.token_urlsafe(32)

    def set(self, token: str, provider: str, api_key: str) -> None:
        with self._lock:
            self._by_token.setdefault(token, {})[provider] = api_key

    def get(self, token: str, provider: str) -> str | None:
        with self._lock:
            return self._by_token.get(token, {}).get(provider)

    def keys_for(self, token: str) -> dict[str, str]:
        """A COPY of this token's ``{provider: key}`` (empty if token unknown)."""
        with self._lock:
            return dict(self._by_token.get(token, {}))

    def has_any(self, token: str) -> bool:
        with self._lock:
            return bool(self._by_token.get(token))

    def clear(self, token: str) -> None:
        with self._lock:
            self._by_token.pop(token, None)
