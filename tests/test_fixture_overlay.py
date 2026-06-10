# tests/test_fixture_overlay.py
import subprocess
import pytest
from abench import fixture as fx

def _mkfixture(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "Main.java").write_text("class Main {}\n")
    return src

def _mkoverlay(tmp_path):
    ov = tmp_path / "ov"
    (ov / ".opencode" / "tools").mkdir(parents=True)
    (ov / ".opencode" / "tools" / "impact.ts").write_text('const s = `${x}`;\n')  # literal ${} survives
    (ov / ".opencode" / "impact.json.tmpl").write_text('{"harness_path": "${GT_HOME}"}\n')
    return ov

def test_overlay_copied_rendered_and_seed_committed(tmp_path):
    src, ov = _mkfixture(tmp_path), _mkoverlay(tmp_path)
    wd, _sha = fx.create_workdir(src, overlay_dir=ov, overlay_env={"GT_HOME": "/opt/gt"})
    try:
        assert (wd / ".opencode" / "impact.json").read_text() == '{"harness_path": "/opt/gt"}\n'
        assert not (wd / ".opencode" / "impact.json.tmpl").exists()
        assert (wd / ".opencode" / "tools" / "impact.ts").read_text() == 'const s = `${x}`;\n'
        tracked = subprocess.run(["git", "ls-tree", "-r", "--name-only", "HEAD"],
                                 cwd=wd, capture_output=True, text=True).stdout
        assert ".opencode/impact.json" in tracked          # seed commit includes overlay
        assert fx.diff_workdir(wd) == ""                   # overlay is not "agent changes"
    finally:
        fx.cleanup(wd)

def test_unknown_tmpl_var_raises_with_names(tmp_path):
    src, ov = _mkfixture(tmp_path), _mkoverlay(tmp_path)
    with pytest.raises(RuntimeError, match=r"impact\.json\.tmpl.*GT_HOME"):
        fx.create_workdir(src, overlay_dir=ov, overlay_env={})

def test_impact_dir_excluded_from_diff(tmp_path):
    src = _mkfixture(tmp_path)
    wd, _ = fx.create_workdir(src)
    try:
        (wd / ".impact").mkdir()
        (wd / ".impact" / "cache.json").write_text("{}")
        assert fx.diff_workdir(wd) == ""
        assert fx.made_source_changes(wd) is False
    finally:
        fx.cleanup(wd)
