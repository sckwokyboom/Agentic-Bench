import json
from pathlib import Path

import abench.bench  # registers adapters
from abench.bench import registry


def _fake_dataset(tmp_path: Path) -> Path:
    """Two NATIVE Multi-SWE-bench records (jackson-core + gson)."""
    def _rec(org, repo, number, f2p_key):
        return {
            "org": org, "repo": repo, "number": number,
            "state": "closed", "title": f"Bug in {repo}",
            "body": f"{repo} misbehaves on empty input.",
            "hints": "GOLDLEAK_the fix adds a null-check in ParserBase.nextToken (from fix_patch)",
            "base": {"label": f"{org}:main", "ref": "main", "sha": f"sha-{number}"},
            "resolved_issues": [{"number": number - 1, "title": "linked", "body": "issue body"}],
            "fix_patch": "diff --git a/src/main/java/A.java b/src/main/java/A.java\n@@ -1 +1 @@\n-a\n+b\n",
            "test_patch": "diff --git a/src/test/java/ATest.java b/src/test/java/ATest.java\n@@ -1 +1,2 @@\n x\n+y\n",
            "f2p_tests": {f2p_key: {"run": "PASS", "test": "FAIL", "fix": "PASS"}},
            "p2p_tests": {}, "s2p_tests": {}, "n2p_tests": {}, "fixed_tests": {},
            "run_result": {"passed_count": 0, "failed_count": 0, "skipped_count": 0,
                           "passed_tests": [], "failed_tests": [], "skipped_tests": []},
            "test_patch_result": {"passed_count": 0, "failed_count": 1, "skipped_count": 0,
                                  "passed_tests": [], "failed_tests": [f2p_key], "skipped_tests": []},
            "fix_patch_result": {"passed_count": 1, "failed_count": 0, "skipped_count": 0,
                                 "passed_tests": [f2p_key], "failed_tests": [], "skipped_tests": []},
        }
    recs = [
        _rec("fasterxml", "jackson-core", 964, "com.fasterxml.jackson.core.ATest"),
        _rec("google", "gson", 2222, "com.google.gson.BTest"),
    ]
    f = tmp_path / "java-verified.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    return f


def test_swebench_registered():
    assert "swebench-java" in registry.available()


def test_load_all_instances(tmp_path: Path):
    adapter = registry.get_adapter("swebench-java")
    insts = list(adapter.load(_fake_dataset(tmp_path), None))
    assert {i.instance_id for i in insts} == {
        "fasterxml/jackson-core:pr-964", "google/gson:pr-2222"}


def test_load_subset_filters_by_repo(tmp_path: Path):
    adapter = registry.get_adapter("swebench-java")
    insts = list(adapter.load(_fake_dataset(tmp_path), {"repo": "fasterxml/jackson-core"}))
    assert len(insts) == 1 and insts[0].repo == "fasterxml/jackson-core"


def test_load_native_instance(tmp_path: Path):
    adapter = registry.get_adapter("swebench-java")
    inst = list(adapter.load(_fake_dataset(tmp_path), {"repo": "fasterxml/jackson-core"}))[0]
    assert inst.instance_id == "fasterxml/jackson-core:pr-964"
    assert inst.env.build_system == "maven"
    assert inst.env.image == "mswebench/fasterxml_m_jackson-core:pr-964"
    # firewall: gold + hidden tests only in oracle
    assert inst.oracle["fix_patch"].startswith("diff --git")
    assert inst.oracle["test_patch"].startswith("diff --git")
    assert inst.oracle["base_sha"] == "sha-964"
    assert "com.fasterxml.jackson.core.ATest" in inst.oracle["f2p_tests"]
    assert inst.oracle["record"]["number"] == 964
    assert not hasattr(inst.agent_view(), "oracle")
    # prompt = issue only; no gold/tests
    p = inst.task.prompt_text
    assert "Bug in jackson-core" in p and "empty input" in p
    assert "diff --git" not in p and "ATest" not in p
    assert "GOLDLEAK" not in p          # native `hints` field is gold/test-derived — never shown
    assert "ParserBase" not in p


def test_load_requires_dataset():
    import pytest
    adapter = registry.get_adapter("swebench-java")
    with pytest.raises(ValueError, match="dataset"):
        list(adapter.load(None, None))


import abench.bench.swebench_java as sj


_DIFF = """diff --git a/src/main/java/com/x/A.java b/src/main/java/com/x/A.java
index 111..222 100644
--- a/src/main/java/com/x/A.java
+++ b/src/main/java/com/x/A.java
@@ -1,1 +1,1 @@
-old
+new
diff --git a/src/test/java/com/x/ATest.java b/src/test/java/com/x/ATest.java
index 333..444 100644
--- a/src/test/java/com/x/ATest.java
+++ b/src/test/java/com/x/ATest.java
@@ -1,1 +1,2 @@
 existing
+assertThat(...)
"""


def test_split_source_test_diff():
    source, test = sj.split_source_test_diff(_DIFF)
    # source-diff keeps the main-source file, drops the test file
    assert "src/main/java/com/x/A.java" in source
    assert "ATest.java" not in source
    # test-diff keeps the test file, drops the main-source file
    assert "src/test/java/com/x/ATest.java" in test
    assert "src/main/java/com/x/A.java" not in test


def test_split_empty_and_source_only():
    assert sj.split_source_test_diff("") == ("", "")
    only_src = "diff --git a/src/main/java/A.java b/src/main/java/A.java\n@@ -1 +1 @@\n-a\n+b\n"
    source, test = sj.split_source_test_diff(only_src)
    assert "A.java" in source and test == ""


def test_split_space_in_test_path_does_not_leak():
    # git does NOT quote plain spaces; the agent's own test file with a space must
    # still be classified as TEST (never leak into the graded source-diff).
    d = (
        "diff --git a/src/test/java/com/x/A Test.java b/src/test/java/com/x/A Test.java\n"
        "--- a/src/test/java/com/x/A Test.java\n"
        "+++ b/src/test/java/com/x/A Test.java\n"
        "@@ -1 +1,2 @@\n x\n+y\n"
    )
    source, test = sj.split_source_test_diff(d)
    assert "A Test.java" in test
    assert "A Test.java" not in source          # firewall: NOT in the graded bucket


def test_split_space_in_source_path_still_graded():
    d = (
        "diff --git a/src/main/java/com/x/A B.java b/src/main/java/com/x/A B.java\n"
        "--- a/src/main/java/com/x/A B.java\n"
        "+++ b/src/main/java/com/x/A B.java\n"
        "@@ -1 +1 @@\n-a\n+b\n"
    )
    source, test = sj.split_source_test_diff(d)
    assert "A B.java" in source
    assert test == ""


def test_split_integration_test_is_test():
    d = (
        "diff --git a/jib-core/src/integration-test/java/com/x/LocalRegistry.java "
        "b/jib-core/src/integration-test/java/com/x/LocalRegistry.java\n"
        "--- a/jib-core/src/integration-test/java/com/x/LocalRegistry.java\n"
        "+++ b/jib-core/src/integration-test/java/com/x/LocalRegistry.java\n"
        "@@ -1 +1,2 @@\n x\n+y\n"
    )
    source, test = sj.split_source_test_diff(d)
    assert "LocalRegistry.java" in test
    assert "LocalRegistry.java" not in source


def test_split_rename_to_test_path_is_test():
    # rename-only section (no @@ hunk): classify by the NEW (rename to) path.
    d = (
        "diff --git a/src/main/java/Helper.java b/src/test/java/HelperTest.java\n"
        "similarity index 100%\n"
        "rename from src/main/java/Helper.java\n"
        "rename to src/test/java/HelperTest.java\n"
    )
    source, test = sj.split_source_test_diff(d)
    assert "src/test/java/HelperTest.java" in test
    assert "Helper" not in source


def test_split_deleted_test_file_is_test():
    d = (
        "diff --git a/src/test/java/GoneTest.java b/src/test/java/GoneTest.java\n"
        "deleted file mode 100644\n"
        "--- a/src/test/java/GoneTest.java\n"
        "+++ /dev/null\n"
        "@@ -1 +0,0 @@\n-x\n"
    )
    source, test = sj.split_source_test_diff(d)
    assert "GoneTest.java" in test
    assert "GoneTest.java" not in source


def _prep(tmp_path):
    ds = _fake_dataset(tmp_path)
    adapter = registry.get_adapter("swebench-java")
    inst = list(adapter.load(ds, {"repo": "fasterxml/jackson-core"}))[0]
    workdir = tmp_path / "wd"
    workdir.mkdir()
    return adapter, inst, workdir


_AGENT_DIFF = (
    "diff --git a/src/main/java/A.java b/src/main/java/A.java\n@@ -1 +1 @@\n-a\n+b\n"
    "diff --git a/src/test/java/ATest.java b/src/test/java/ATest.java\n@@ -1 +1,2 @@\n x\n+y\n"
)


def _mock_both_graders(monkeypatch, *, official_resolved, seen=None,
                       abench_ret=None):
    """Mock BOTH grade seams. `seen` (if given) captures what the official
    evaluator received, to prove only the source-diff is sent."""
    def _fake_official(oracle, source_diff):
        if seen is not None:
            seen["source_diff"] = source_diff
        return {"resolved": official_resolved, "report": {}}
    monkeypatch.setattr(sj, "_run_swebench_evaluator", _fake_official)
    monkeypatch.setattr(
        sj, "_run_abench_verify",
        lambda oracle, source_diff, test_diff, workdir: (
            abench_ret if abench_ret is not None
            else {"scoped_regressions": [], "repro_reproduced": True,
                  "abench_resolved": official_resolved}))


def test_grade_official_verdict_and_source_only_delegation(tmp_path, monkeypatch):
    adapter, inst, workdir = _prep(tmp_path)
    seen = {}
    _mock_both_graders(monkeypatch, official_resolved=True, seen=seen)
    g = adapter.grade(inst, _AGENT_DIFF, workdir)
    # headline verdict = OFFICIAL only
    assert g.resolved is True
    assert g.standard_protocol is True
    assert g.evaluator.startswith("multi-swe-bench")
    assert g.official_report["resolved"] is True
    # only the SOURCE diff reached the official evaluator — the agent's test edit
    # is stripped (firewall / no grade-gaming)
    assert "src/main/java/A.java" in seen["source_diff"]
    assert "ATest.java" not in seen["source_diff"]


def test_grade_carries_abench_own_methodology(tmp_path, monkeypatch):
    adapter, inst, workdir = _prep(tmp_path)
    _mock_both_graders(monkeypatch, official_resolved=True, abench_ret={
        "scoped_regressions": ["com.x.OtherTest#t"], "repro_reproduced": True,
        "abench_resolved": False})
    g = adapter.grade(inst, _AGENT_DIFF, workdir)
    # dual-grading: abench's OWN methodology is first-class, alongside official
    assert g.abench["scoped_regressions"] == ["com.x.OtherTest#t"]
    assert g.abench["repro_reproduced"] is True
    assert g.abench["abench_resolved"] is False        # abench's separate cross-check
    assert g.abench["test_diff_present"] is True        # agent wrote a repro test
    assert g.abench["n_fail_to_pass"] == 1
    # abench's cross-check verdict must NOT override the exported (official) number
    assert g.resolved is True


def test_grade_not_resolved(tmp_path, monkeypatch):
    adapter, inst, workdir = _prep(tmp_path)
    _mock_both_graders(monkeypatch, official_resolved=False)
    g = adapter.grade(inst, _AGENT_DIFF, workdir)
    assert g.resolved is False
    assert g.standard_protocol is True
