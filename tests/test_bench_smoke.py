from pathlib import Path

import abench.bench  # noqa: F401  (triggers smoke registration)
from abench.bench import registry


def test_smoke_registered():
    assert "smoke" in registry.available()


def test_smoke_roundtrip(tmp_path: Path):
    adapter = registry.get_adapter("smoke")
    inst = list(adapter.load(dataset=None, subset=None))[0]
    view = inst.agent_view()

    adapter.materialize(view, tmp_path)
    assert (tmp_path / "calc.py").exists()

    # Unsolved fixture: grade fails.
    g0 = adapter.grade(inst, source_diff="", workdir=tmp_path)
    assert g0.resolved is False

    # Apply the fix, grade passes.
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    g1 = adapter.grade(inst, source_diff="+ return a + b", workdir=tmp_path)
    assert g1.resolved is True
    assert g1.standard_protocol is True
    assert g1.abench["made_source_changes"] is True
