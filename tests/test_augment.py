import importlib.util
import sys
import types
from pathlib import Path

import pytest

# Load scripts/augment.py by path (scripts/ is not an importable package under pytest,
# matching tests/test_export_chain_snippets.py).
SCRIPT = Path(__file__).parents[1] / "scripts" / "augment.py"
SPEC = importlib.util.spec_from_file_location("augment", SCRIPT)
aug = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = aug
assert SPEC.loader is not None
SPEC.loader.exec_module(aug)


def test_resolve_gt_registry(monkeypatch, tmp_path):
    monkeypatch.setattr(aug, "_registry_gt", lambda: tmp_path)
    assert aug.resolve_gt() == tmp_path


def test_resolve_gt_env_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(aug, "_registry_gt", lambda: None)
    monkeypatch.setenv("GRAPH_TIPPER_HOME", str(tmp_path))
    assert aug.resolve_gt() == tmp_path


def test_resolve_gt_unresolved(monkeypatch):
    monkeypatch.setattr(aug, "_registry_gt", lambda: None)
    monkeypatch.delenv("GRAPH_TIPPER_HOME", raising=False)
    with pytest.raises(SystemExit):
        aug.resolve_gt()


def test_run_builds_command_and_copies(monkeypatch, tmp_path):
    gt = tmp_path / "gt"; gt.mkdir()
    exp = tmp_path / "exp"; (exp / "slices").mkdir(parents=True)
    pool = tmp_path / "pool"; pool.mkdir()
    (pool / "augment.prompt.md").write_text("BUNDLE")
    calls = {}

    def fake_run(cmd, **kw):
        calls["cmd"] = cmd
        calls["cwd"] = str(kw.get("cwd"))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(aug, "resolve_gt", lambda: gt)
    monkeypatch.setattr(aug.subprocess, "run", fake_run)
    aug.run(project="/p", target="C.m", experiment=exp, out=pool)

    assert "harness.kgpool.make" in calls["cmd"]
    assert "--project" in calls["cmd"] and "/p" in calls["cmd"]
    assert "--target" in calls["cmd"] and "C.m" in calls["cmd"]
    assert calls["cwd"] == str(gt)
    assert (exp / "slices/augment.prompt.md").read_text() == "BUNDLE"
