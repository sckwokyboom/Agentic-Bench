import json
from pathlib import Path

import abench.bench  # registers adapters
from abench.bench import registry


def _fake_dataset(tmp_path: Path) -> Path:
    """A 2-record SWE-bench-java dataset: one jackson-core, one other repo."""
    records = [
        {
            "repo": "fasterxml/jackson-core",
            "instance_id": "fasterxml__jackson-core-1111",
            "base_commit": "abc123",
            "problem_statement": "NPE in JsonParser when input is empty.",
            "hints_text": "the PR fixed it in ParserBase",   # must NOT reach the agent
            "patch": "diff --git a/src/main/java/A.java ...",   # GOLD
            "test_patch": "diff --git a/src/test/java/ATest.java ...",  # HIDDEN
            "FAIL_TO_PASS": json.dumps(["src:com.fasterxml.jackson.core.ATest"]),
            "PASS_TO_PASS": json.dumps([]),
            "version": "0.1",
        },
        {
            "repo": "google/gson",
            "instance_id": "google__gson-2222",
            "base_commit": "def456",
            "problem_statement": "Gson mishandles nulls.",
            "patch": "diff --git a/gson/src/main/java/B.java ...",
            "test_patch": "diff --git a/gson/src/test/java/BTest.java ...",
            "FAIL_TO_PASS": json.dumps(["gson:com.google.gson.BTest"]),
            "PASS_TO_PASS": json.dumps([]),
            "version": "0.1",
        },
    ]
    f = tmp_path / "swe-bench-java-verified.json"
    f.write_text(json.dumps(records))
    return f


def test_swebench_registered():
    assert "swebench-java" in registry.available()


def test_load_all_instances(tmp_path: Path):
    ds = _fake_dataset(tmp_path)
    adapter = registry.get_adapter("swebench-java")
    insts = list(adapter.load(ds, None))
    assert len(insts) == 2
    ids = {i.instance_id for i in insts}
    assert ids == {"fasterxml__jackson-core-1111", "google__gson-2222"}


def test_load_subset_filters_by_repo(tmp_path: Path):
    ds = _fake_dataset(tmp_path)
    adapter = registry.get_adapter("swebench-java")
    insts = list(adapter.load(ds, {"repo": "fasterxml/jackson-core"}))
    assert len(insts) == 1
    assert insts[0].repo == "fasterxml/jackson-core"


def test_firewall_oracle_holds_gold_and_tests_agentview_does_not(tmp_path: Path):
    ds = _fake_dataset(tmp_path)
    adapter = registry.get_adapter("swebench-java")
    inst = list(adapter.load(ds, {"repo": "fasterxml/jackson-core"}))[0]
    # oracle carries gold/hidden data (grade-only)
    assert inst.oracle["patch"].startswith("diff --git")
    assert inst.oracle["test_patch"].startswith("diff --git")
    assert inst.oracle["base_commit"] == "abc123"
    # F2P/P2P decoded from JSON-encoded STRINGS into real lists
    assert inst.oracle["fail_to_pass"] == ["src:com.fasterxml.jackson.core.ATest"]
    assert inst.oracle["pass_to_pass"] == []
    # firewall: agent_view() has no oracle at all
    assert not hasattr(inst.agent_view(), "oracle")
    # neither gold nor hidden tests nor hints leak into the agent-visible prompt
    prompt = inst.task.prompt_text
    assert "NPE in JsonParser" in prompt                 # the issue IS shown
    assert "ParserBase" not in prompt                    # hints_text NOT shown
    assert "diff --git" not in prompt                    # gold/test patch NOT shown
    assert "ATest" not in prompt                         # FAIL_TO_PASS NOT shown


def test_env_per_instance(tmp_path: Path):
    ds = _fake_dataset(tmp_path)
    adapter = registry.get_adapter("swebench-java")
    inst = list(adapter.load(ds, {"repo": "fasterxml/jackson-core"}))[0]
    assert inst.env.build_system == "maven"              # jackson = maven
    assert inst.env.image == "mswebench/fasterxml_jackson-core:0.1"


def test_load_requires_dataset():
    import pytest
    adapter = registry.get_adapter("swebench-java")
    with pytest.raises(ValueError, match="dataset"):
        list(adapter.load(None, None))


def test_as_list_rejects_non_list_json():
    import pytest
    from abench.bench.swebench_java import _as_list
    # valid forms still work
    assert _as_list(None) == []
    assert _as_list(json.dumps(["a", "b"])) == ["a", "b"]
    assert _as_list(["x"]) == ["x"]
    # a JSON string that decodes to a non-list must raise, not silently make chars
    with pytest.raises(ValueError):
        _as_list(json.dumps("just_a_word"))
    with pytest.raises(ValueError):
        _as_list(json.dumps({"a": 1}))
