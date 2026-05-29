"""Per-test cache-cleanup so abench_ui.validate's TTLCache decorators don't
carry state across the patch-based tests in test_validate.py."""
from __future__ import annotations

import pytest

from abench_ui import validate


@pytest.fixture(autouse=True)
def _clear_validate_caches():
    """Clear the in-module TTL caches before every test in this package.

    The production behaviour (cache hit between real calls) is preserved;
    only test isolation is enforced."""
    validate._PROVIDERS_CACHE.clear()
    validate._MODELS_CACHE.clear()
    yield
    validate._PROVIDERS_CACHE.clear()
    validate._MODELS_CACHE.clear()
