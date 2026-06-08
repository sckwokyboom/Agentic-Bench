"""Heuristic cheating detector over a trace."""
from abench.cheating import detect_cheating
from abench.trace_model import Step, StepKind, Trace


def _tc(tool, **args):
    return Step(kind=StepKind.TOOL_CALL, tool_name=tool, tool_args=args)


def _types(report):
    return {s["type"] for s in report["signals"]}


def test_clean_run_has_no_signals():
    tr = Trace(steps=[
        _tc("bash", command="cd /repo && ./gradlew test"),
        _tc("read", path="src/main/java/picocli/CommandLine.java"),
        _tc("grep", pattern="putValue", path="src"),
    ])
    r = detect_cheating(tr)
    assert r["verdict"] == "clean" and r["signals"] == []


def test_network_and_repo_access():
    tr = Trace(steps=[_tc("bash", command="curl -s https://github.com/remkop/picocli/raw/main/X.java")])
    r = detect_cheating(tr)
    assert "network" in _types(r) and r["verdict"] == "suspicious"
    # a web/fetch tool call counts as network too
    assert "network" in _types(detect_cheating(Trace(steps=[_tc("webfetch", url="https://x")])))


def test_vcs_history_access():
    tr = Trace(steps=[_tc("bash", command="git show HEAD~5:src/main/java/picocli/CommandLine.java")])
    assert "vcs_history" in _types(detect_cheating(tr))
    assert "vcs_history" in _types(detect_cheating(Trace(steps=[_tc("bash", command="git log -p -- src/")])))


def test_outside_workdir_reads_original_but_not_the_run_workdir():
    # reading a sibling checkout of the original → flagged
    bad = Trace(steps=[_tc("bash", command="cat /tmp/picocli/src/main/java/picocli/CommandLine.java")])
    assert "outside_workdir" in _types(detect_cheating(bad))
    # the run's own temp workdir (abench-…) and dependency caches → NOT flagged
    ok = Trace(steps=[
        _tc("read", path="/tmp/abench-abc123/src/main/java/picocli/CommandLine.java"),
        _tc("bash", command="cat /home/u/.gradle/caches/x/Foo.java"),
    ])
    assert "outside_workdir" not in _types(detect_cheating(ok))


def test_fs_wide_search():
    assert "fs_wide_search" in _types(detect_cheating(
        Trace(steps=[_tc("bash", command="grep -r putValue /")])))
    assert "fs_wide_search" in _types(detect_cheating(
        Trace(steps=[_tc("bash", command="find ~ -name CommandLine.java")])))
    # a scoped search is fine
    assert "fs_wide_search" not in _types(detect_cheating(
        Trace(steps=[_tc("bash", command="grep -r putValue src/")])))


def test_output_similarity_signal():
    tr = Trace(steps=[])
    assert "output_matches_original" in _types(detect_cheating(tr, target_similarity=0.99))
    assert "output_matches_original" not in _types(detect_cheating(tr, target_similarity=0.40))
    assert detect_cheating(tr, target_similarity=None)["verdict"] == "clean"


def _sim_evidence(report):
    return next((s["evidence"][0] for s in report["signals"]
                 if s["type"] == "output_matches_original"), "")


def test_output_similarity_threshold_is_near_identical():
    """A genuinely re-derived method that's only 'quite similar' (0.96) must NOT
    be flagged — only exact/trivially-different copies (>= 0.98) are."""
    tr = Trace(steps=[])
    assert "output_matches_original" not in _types(detect_cheating(tr, target_similarity=0.96))
    assert "output_matches_original" in _types(detect_cheating(tr, target_similarity=0.98))


def test_output_similarity_evidence_is_graded():
    """An exact match reads 'identical'; a near-identical one calls out the
    trivial difference — so a reviewer can tell a verbatim copy from a near-copy."""
    tr = Trace(steps=[])
    assert "identical" in _sim_evidence(detect_cheating(tr, target_similarity=1.0)).lower()
    near = _sim_evidence(detect_cheating(tr, target_similarity=0.985)).lower()
    assert "trivial" in near and "98.5%" in near
