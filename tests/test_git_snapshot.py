import os
import subprocess
from pathlib import Path

import pytest

from abench.git_snapshot import (
    snapshot, restore, restore_except, strip_marked_lines, forbidden_changes,
    _git as _git_call,
)


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


def test_restore_except_keeps_target_strips_everything_else(tmp_path):
    """forced-instrument guard: the agent's edit to the target file is kept,
    while test instrumentation (modified test) and scratch files (untracked) are
    reverted/removed, and gitignored build output survives."""
    r = _repo(tmp_path)
    (r / "build").mkdir()
    (r / "build" / "out.class").write_text("cached\n")
    (r / ".gitignore").write_text("build/\n")
    _git(r, "add", "-A"); _git(r, "commit", "-qm", "with-build")
    # agent activity
    (r / "src" / "A.java").write_text("NEW_IMPL\n")            # target edit (keep)
    (r / "src" / "D.java").write_text("orig\n// [probe]\n")    # test instrumentation (strip)
    (r / "src" / "Scratch.java").write_text("scratch\n")       # untracked scratch (strip)
    (r / "build" / "out.class").write_text("recompiled\n")     # gitignored (keep)

    restore_except(r, ["src/A.java"])

    assert (r / "src" / "A.java").read_text() == "NEW_IMPL\n"   # target kept
    assert (r / "src" / "D.java").read_text() == "dee\n"        # instrumentation reverted
    assert not (r / "src" / "Scratch.java").exists()            # scratch removed
    assert (r / "build" / "out.class").read_text() == "recompiled\n"  # build/ untouched


def test_restore_except_is_noop_when_only_target_changed(tmp_path):
    """Baseline never edits outside the target, so the guard must not perturb
    anything (no confound in the A/B)."""
    r = _repo(tmp_path)
    (r / "src" / "A.java").write_text("only target changed\n")
    before_d = (r / "src" / "D.java").read_text()
    restore_except(r, ["src/A.java"])
    assert (r / "src" / "A.java").read_text() == "only target changed\n"
    assert (r / "src" / "D.java").read_text() == before_d


def test_strip_marked_lines_removes_only_marked(tmp_path):
    """forced-instrument code-probe guard: lines carrying the //[probe] marker are
    removed from the graded target; the real implementation is untouched."""
    p = tmp_path / "T.java"
    p.write_text(
        "int x = compute();\n"
        'System.out.println("[probe] x=" + x);  //[probe]\n'
        "return x;\n"
        "doThing();  //[probe] inline trailing probe\n"
        "int y = 2;\n"
    )
    removed = strip_marked_lines(tmp_path, "T.java")
    assert removed == 2
    assert p.read_text() == "int x = compute();\nreturn x;\nint y = 2;\n"


def test_strip_marked_lines_noop_without_marker(tmp_path):
    p = tmp_path / "T.java"
    src = "int x = compute();\nreturn x;\n"
    p.write_text(src)
    assert strip_marked_lines(tmp_path, "T.java") == 0
    assert p.read_text() == src


def test_strip_marked_lines_missing_file_is_noop(tmp_path):
    assert strip_marked_lines(tmp_path, "does/not/exist.java") == 0


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
