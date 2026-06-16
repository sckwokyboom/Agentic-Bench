"""The augmented-tool condition's `impact` tool reads precomputed data from
experiments/picocli-putValue/overlays/impact-artifacts/.impact/. That data was
once gitignored, so it never reached the server — the tool then had nothing to
read and returned empty output, making the whole condition meaningless. Guard
that the data stays committed and that the tool config's referenced files exist
and parse."""
import json
from pathlib import Path

import pytest

_OVERLAY = (
    Path(__file__).resolve().parents[1]
    / "experiments" / "picocli-putValue" / "overlays" / "impact-artifacts"
)

pytestmark = pytest.mark.skipif(
    not (_OVERLAY / ".opencode" / "impact.json").is_file(),
    reason="picocli-putValue impact overlay not present",
)


def test_impact_config_references_existing_data():
    """Every data path the tool config names must resolve to a file that parses
    (this is what the tool reads at runtime — if missing, it returns nothing)."""
    cfg = json.loads((_OVERLAY / ".opencode" / "impact.json").read_text())
    base = _OVERLAY / ".opencode"
    for key in ("methods", "coverage", "mutation"):
        p = (base / cfg[key]).resolve()
        assert p.is_file(), f"impact data '{key}' -> {cfg[key]} missing at {p}"
        json.loads(p.read_text())  # must be valid JSON


def test_impact_methods_and_coverage_are_populated():
    """methods + coverage carry the actual signal (mutation may legitimately be
    empty); if these are empty the tool has nothing useful to say."""
    d = _OVERLAY / ".impact"
    methods = json.loads((d / "methods.json").read_text())
    coverage = json.loads((d / "coverage.json").read_text())
    assert len(methods) > 100, "methods.json should map the project's methods"
    assert len(coverage) > 0, "coverage.json should map tests to covered methods"
