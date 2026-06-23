import subprocess
from pathlib import Path
from abench.git_snapshot import snapshot, restore, forbidden_changes


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


def test_forbidden_changes_flags_non_allowlisted_paths(tmp_path):
    r = _repo(tmp_path)
    (r / "src" / "A.java").write_text("edit\n")              # allowed
    (r / "build.gradle").write_text("x")                     # forbidden
    (r / "t.txt").write_text("y")                            # forbidden
    bad = forbidden_changes(r, allowed_prefixes=["src/"])
    assert "build.gradle" in bad and "t.txt" in bad and "src/A.java" not in bad
