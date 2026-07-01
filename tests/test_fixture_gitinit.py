import subprocess
from pathlib import Path

from abench.fixture import _git_init_commit


def test_git_init_commit_creates_repo_and_returns_sha(tmp_path: Path):
    (tmp_path / "a.txt").write_text("hello\n")
    sha = _git_init_commit(tmp_path)
    assert isinstance(sha, str) and len(sha) == 40
    assert (tmp_path / ".git").is_dir()
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert head == sha
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=tmp_path,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert status == ""
