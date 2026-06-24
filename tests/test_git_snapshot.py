import os
import subprocess
from pathlib import Path

import pytest

from abench.git_snapshot import snapshot, restore, forbidden_changes, _git as _git_call


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True,
                   capture_output=True, text=True)


def _repo(tmp_path) -> Path:
    r = tmp_path / "wd"; r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t"); _git(r, "config", "user.name", "t")
    (r / "src").mkdir()
    (r / "src" / "A.java").write_text("orig\n")
    (r / "src" / "D.java").write_text("dee\n")
    _git(r, "add", "-A"); _git(r, "commit", "-qm", "seed")
    return r


def test_restore_reverts_modify_create_and_delete(tmp_path):
    r = _repo(tmp_path)
    snap = snapshot(r)
    (r / "src" / "A.java").write_text("changed\n")          # modify tracked
    (r / "src" / "B.java").write_text("new\n")               # create untracked
    (r / "src" / "D.java").unlink()                          # delete tracked
    (r / "C.txt").write_text("c"); _git(r, "add", "C.txt")   # stage a new file
    restore(r, snap)
    assert (r / "src" / "A.java").read_text() == "orig\n"    # modify reverted
    assert (r / "src" / "D.java").read_text() == "dee\n"     # delete restored
    assert not (r / "src" / "B.java").exists()               # untracked removed
    assert not (r / "C.txt").exists()                        # staged-new removed


def test_restore_removes_untracked_nested_git_repo(tmp_path):
    """An untracked nested git repo (e.g. opencode/tool state) makes plain
    `git clean -fd` refuse + exit non-zero, which crashed the diagnose loop.
    -ffd removes it; restore must succeed and still revert tracked source."""
    r = _repo(tmp_path)
    snap = snapshot(r)
    (r / "src" / "A.java").write_text("changed\n")          # modify tracked
    nested = r / "toolstate"; nested.mkdir()
    _git(nested, "init", "-q")                              # untracked nested repo
    (nested / "x.txt").write_text("y\n")
    restore(r, snap)                                        # must NOT raise
    assert (r / "src" / "A.java").read_text() == "orig\n"   # tracked reverted
    assert not nested.exists()                              # nested repo cleaned


def test_restore_tolerates_unremovable_untracked(tmp_path):
    """If git clean can't remove an untracked file (root-owned from the container,
    or a locked Windows/WSL handle), restore must not abort the run — the tracked
    source is already reverted before clean."""
    r = _repo(tmp_path)
    snap = snapshot(r)
    (r / "src" / "A.java").write_text("changed\n")
    pinned = r / "src" / "pinned"; pinned.mkdir()
    (pinned / "x.txt").write_text("y\n")                    # untracked
    os.chmod(pinned, 0o500)                                 # un-writable dir → clean can't unlink
    try:
        restore(r, snap)                                   # must NOT raise
        assert (r / "src" / "A.java").read_text() == "orig\n"   # tracked still reverted
    finally:
        os.chmod(pinned, 0o700)                            # allow tmp cleanup


def test_git_failure_surfaces_stderr(tmp_path):
    """A git failure carries its stderr in the message (not a bare exit code), so
    run logs say WHY it failed."""
    nonrepo = tmp_path / "x"; nonrepo.mkdir()
    with pytest.raises(RuntimeError) as ei:
        _git_call(nonrepo, "status")
    assert "git status failed" in str(ei.value)


def test_forbidden_changes_flags_non_allowlisted_paths(tmp_path):
    r = _repo(tmp_path)
    (r / "src" / "A.java").write_text("edit\n")              # allowed
    (r / "build.gradle").write_text("x")                     # forbidden
    (r / "t.txt").write_text("y")                            # forbidden
    bad = forbidden_changes(r, allowed_prefixes=["src/"])
    assert "build.gradle" in bad and "t.txt" in bad and "src/A.java" not in bad
