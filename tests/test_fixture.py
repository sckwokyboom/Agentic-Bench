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


def test_diff_workdir_survives_binary_and_latin1_and_excludes_build(tmp_path):
    # Regression: an agent that runs mvn/gradle fills target/ with binary .class
    # files and latin-1 resources. A strict-UTF-8 decode of the diff crashed the
    # run AFTER the agent had already produced a fix (seen on Defects4J Time-14).
    src = tmp_path / "proj"
    (src / "src").mkdir(parents=True)
    (src / "src" / "A.java").write_text("class A {}\n")
    workdir, _ = fx.create_workdir(src, parent=tmp_path)

    # Agent edits real source (must appear in the diff)…
    (workdir / "src" / "A.java").write_text("class A { int x; }\n")
    # …and a build produces target/ with a binary class + a latin-1 resource.
    (workdir / "target" / "classes").mkdir(parents=True)
    (workdir / "target" / "classes" / "A.class").write_bytes(bytes(range(256)))
    (workdir / "target" / "messages_es.properties").write_bytes(
        "a\xf1o=year\n".encode("latin-1"))          # 0xf1 is invalid UTF-8

    diff = fx.diff_workdir(workdir)                  # must NOT raise
    assert "src/A.java" in diff                      # real source change kept
    assert "target/" not in diff and ".class" not in diff  # build output excluded
    fx.cleanup(workdir)


def test_diff_workdir_excludes_tool_output_at_root_and_nested(tmp_path):
    # Regression from the first Defects4J sieve: the diffstat metric reported a
    # 545-file "+8303-line fix" that was gradle cache, and 187 surefire reports in
    # another. Root-anchored and nested forms BOTH matter — 'target/**' misses a
    # multi-module 'gson/target/**', while '**/.gradle/**' misses a root '.gradle/'.
    src = tmp_path / "proj"
    (src / "gson" / "src").mkdir(parents=True)
    (src / "gson" / "src" / "T.java").write_text("class T {}\n")
    wd, _ = fx.create_workdir(src, parent=tmp_path)
    (wd / "gson" / "src" / "T.java").write_text("class T { int x; }\n")
    for rel in ("gson/target/surefire-reports/T.xml",   # nested maven output
                ".gradle_local_home/caches/junit.pom",  # root gradle cache
                ".gradle/buildOutputCleanup/c.properties",
                "buildSrc/.gradle/c.properties",        # nested gradle
                "target/classes/A.class",
                "lib/x.jar",
                "all_tests", "failing_tests",           # Defects4J's own verdict
                "TESTS-TestSuites.xml"):                # ant test report
        p = wd / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("noise\n")
    paths = {ln.split(" b/")[-1] for ln in fx.diff_workdir(wd).splitlines()
             if ln.startswith("diff --git ")}
    assert paths == {"gson/src/T.java"}, f"tool output leaked into the diff: {paths}"
    fx.cleanup(wd)
