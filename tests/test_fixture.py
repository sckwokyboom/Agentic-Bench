# tests/test_fixture.py
import subprocess
from pathlib import Path

from abench import fixture as fx


def _make_fixture(tmp_path: Path) -> Path:
    src = tmp_path / "proj"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "mod.py").write_text("def f():\n    ...\n")
    # a stale .git that MUST be stripped (leak guard)
    (src / ".git").mkdir()
    (src / ".git" / "HEAD").write_text("ref: refs/heads/secret\n")
    return src


def test_create_workdir_strips_git_and_commits(tmp_path):
    src = _make_fixture(tmp_path)
    workdir, sha = fx.create_workdir(src, parent=tmp_path)
    assert (workdir / "pkg" / "mod.py").exists()
    # original .git stripped, fresh repo has exactly one commit
    log = subprocess.run(["git", "log", "--oneline"], cwd=workdir,
                         capture_output=True, text=True, check=True).stdout
    assert log.count("\n") == 1
    assert sha
    fx.cleanup(workdir)
    assert not workdir.exists()


def test_diff_workdir_reports_changes(tmp_path):
    src = _make_fixture(tmp_path)
    workdir, _ = fx.create_workdir(src, parent=tmp_path)
    (workdir / "pkg" / "mod.py").write_text("def f():\n    return 1\n")
    (workdir / "new.txt").write_text("hello\n")
    patch = fx.diff_workdir(workdir)
    assert "pkg/mod.py" in patch
    assert "new.txt" in patch
    assert "+    return 1" in patch
    fx.cleanup(workdir)


def test_diff_workdir_excludes_opencode_artifacts(tmp_path):
    """opencode writes opencode.json + .opencode/ INTO the workdir; those must
    never pollute the agent's source diff."""
    src = _make_fixture(tmp_path)
    workdir, _ = fx.create_workdir(src, parent=tmp_path)
    # Real source change
    (workdir / "pkg" / "mod.py").write_text("def f():\n    return 1\n")
    # opencode artifacts
    (workdir / "opencode.json").write_text('{"model": "x"}\n')
    (workdir / ".opencode").mkdir()
    (workdir / ".opencode" / "state").write_text("opaque\n")
    patch = fx.diff_workdir(workdir)
    assert "pkg/mod.py" in patch          # real source survives
    assert "opencode.json" not in patch   # artifact excluded
    assert ".opencode" not in patch       # artifact dir excluded
    assert fx.made_source_changes(workdir) is True
    fx.cleanup(workdir)


def test_diff_workdir_empty_when_only_opencode_artifacts(tmp_path):
    """If the agent made no source edits and only opencode artifacts exist,
    the diff is empty and made_source_changes is False."""
    src = _make_fixture(tmp_path)
    workdir, _ = fx.create_workdir(src, parent=tmp_path)
    (workdir / "opencode.json").write_text('{"model": "x"}\n')
    (workdir / ".opencode").mkdir()
    (workdir / ".opencode" / "state").write_text("opaque\n")
    patch = fx.diff_workdir(workdir)
    assert patch.strip() == ""
    assert fx.made_source_changes(workdir) is False
    fx.cleanup(workdir)
