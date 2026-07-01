"""Adapter registry: id -> BenchmarkAdapter."""
from __future__ import annotations

from .base import BenchmarkAdapter

_REGISTRY: dict[str, BenchmarkAdapter] = {}


def register(adapter: BenchmarkAdapter) -> None:
    _REGISTRY[adapter.id] = adapter


def get_adapter(adapter_id: str) -> BenchmarkAdapter:
    try:
        return _REGISTRY[adapter_id]
    except KeyError:
        raise KeyError(
            f"unknown benchmark adapter {adapter_id!r}; "
            f"registered: {sorted(_REGISTRY)}"
        )


def available() -> list[str]:
    return sorted(_REGISTRY)
