"""The sandbox ships a shell `impact` CLI (models instinctively run `bash
impact` rather than calling the opencode tool). It reads .opencode/impact.json +
the uncommitted diff and prints the tests covering each changed method. The CLI
is a self-contained stdlib script (docker/impact_cli.py) loaded here by path."""
import importlib.util
from pathlib import Path

_CLI = Path(__file__).resolve().parents[1] / "docker" / "impact_cli.py"
_spec = importlib.util.spec_from_file_location("impact_cli", _CLI)
impact_cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(impact_cli)


def test_changed_lines_parses_new_side_line_numbers():
    diff = (
        "diff --git a/src/X.java b/src/X.java\n"
        "--- a/src/X.java\n"
        "+++ b/src/X.java\n"
        "@@ -10,2 +10,3 @@\n"
        " context\n"
        "+added1\n"
        "+added2\n"
    )
    ch = impact_cli.changed_lines(diff)
    assert 11 in ch["src/X.java"] and 12 in ch["src/X.java"]  # the two +lines


def test_methods_for_maps_changed_lines_to_the_overlapping_method():
    methods = {
        "pkg.Cls.putValue": {"file": "src/X.java", "start": 10, "end": 20},
        "pkg.Cls.other": {"file": "src/X.java", "start": 30, "end": 40},
    }
    assert impact_cli.methods_for({"src/X.java": {12}}, methods) == ["pkg.Cls.putValue"]


def test_methods_for_matches_by_path_suffix():
    """git diff paths and methods.json paths may differ by a leading dir."""
    methods = {"pkg.Cls.m": {"file": "src/X.java", "start": 1, "end": 5}}
    assert impact_cli.methods_for({"a/b/src/X.java": {3}}, methods) == ["pkg.Cls.m"]


def test_build_report_lists_coverers_and_notes_missing_mutation():
    methods = {"pkg.Cls.putValue": {"file": "src/X.java", "start": 10, "end": 20}}
    coverage = {"pkg.Cls.putValue": ["pkg.HelpTest.tA", "pkg.HelpTest.tB"]}
    report = impact_cli.build_report({"src/X.java": {12}}, methods, coverage, {})
    assert "putValue" in report
    assert "pkg.HelpTest.tA" in report and "pkg.HelpTest.tB" in report
    assert "mutation" in report.lower()  # explicit "no mutation data" note


def test_build_report_handles_no_changed_methods():
    report = impact_cli.build_report({"src/Unknown.java": {1}}, {}, {}, {})
    assert "no " in report.lower()  # a clear "nothing matched" message, not a crash


def test_build_report_ranks_name_matching_tests_first():
    """A coverage list is Tier-2 (anything that *executes* the method), so for a
    broadly-covered method the genuinely relevant tests — those whose NAME echoes
    the method or its innermost class — are buried. Surface them first; that is
    what a capable agent greps for by hand."""
    methods = {"picocli.CommandLine$Help$TextTable.putValue":
               {"file": "src/main/java/picocli/CommandLine.java", "start": 10, "end": 20}}
    coverage = {"picocli.CommandLine$Help$TextTable.putValue": [
        "picocli.AbbreviationMatcherTest.testAbbrevOptions",                 # incidental
        "picocli.HelpTest.testTextTablePutValue_DisallowsInvalidRowIndex",   # matches method + class
        "picocli.ArgGroupTest.testMultipleGroups",                           # incidental
    ]}
    report = impact_cli.build_report(
        {"src/main/java/picocli/CommandLine.java": {12}}, methods, coverage, {})
    listed = [l for l in report.splitlines() if l.strip().startswith("- ")]
    idx_match = next(i for i, l in enumerate(listed) if "testTextTablePutValue" in l)
    idx_incidental = next(i for i, l in enumerate(listed) if "testAbbrevOptions" in l)
    assert idx_match < idx_incidental


def test_build_report_suggests_specific_test_methods_when_name_matches():
    """When a coverer's name matches the changed method, the focused command must
    target that specific test method (Class.method), not just the whole class."""
    methods = {"pkg.Cls.bar": {"file": "src/X.java", "start": 1, "end": 5}}
    coverage = {"pkg.Cls.bar": ["pkg.OtherTest.testUnrelated", "pkg.ClsTest.testBar"]}
    report = impact_cli.build_report({"src/X.java": {3}}, methods, coverage, {})
    assert "--tests 'pkg.ClsTest.testBar'" in report


def test_build_report_falls_back_to_classes_when_no_name_match():
    """With no name-matching coverer, keep the prior class-level suggestion."""
    methods = {"pkg.Cls.bar": {"file": "src/X.java", "start": 1, "end": 5}}
    coverage = {"pkg.Cls.bar": ["pkg.AlphaTest.testOne", "pkg.AlphaTest.testTwo"]}
    report = impact_cli.build_report({"src/X.java": {3}}, methods, coverage, {})
    assert "--tests 'pkg.AlphaTest'" in report          # class-level
    assert "pkg.AlphaTest.testOne'" not in report       # not a specific method


# ── #2 blast-radius calibration + #3 two-tier command ─────────────────────────

def test_build_report_broad_change_steers_to_full_suite():
    """A change covered by many test classes can't be verified by a focused
    subset (it would hide failures elsewhere) — impact must steer to the full
    suite, not a misleading class subset. This is the putValue lesson."""
    methods = {"pkg.Cls.central": {"file": "src/X.java", "start": 1, "end": 5}}
    coverage = {"pkg.Cls.central": [f"pkg.T{i}Test.testThing" for i in range(12)]}  # 12 classes
    report = impact_cli.build_report({"src/X.java": {3}}, methods, coverage, {},
                                     total_tests=2234, test_cmd="./gradlew :test")
    assert "BROAD" in report
    assert "./gradlew :test --continue" in report               # full suite, project verb
    assert "Focused run of the affected test classes" not in report  # no misleading subset


def test_build_report_narrow_change_is_two_tier_focused_then_full():
    """A narrow change gets a focused command for the iterate-loop AND the full
    suite as the done-gate."""
    methods = {"pkg.Cls.bar": {"file": "src/X.java", "start": 1, "end": 5}}
    coverage = {"pkg.Cls.bar": ["pkg.ClsTest.testBar", "pkg.ClsTest.testOther"]}
    report = impact_cli.build_report({"src/X.java": {3}}, methods, coverage, {},
                                     test_cmd="./gradlew :test")
    assert "--tests 'pkg.ClsTest.testBar'" in report            # focused, for iterating
    assert "./gradlew :test --continue" in report               # full-suite done-gate
    assert "BROAD" not in report


def test_build_report_uses_configured_test_command():
    """The emitted command uses the project's configured verb (the trace proved
    a bare `./gradlew test` is wrong for picocli's modules — it needs `:test`)."""
    methods = {"pkg.Cls.bar": {"file": "src/X.java", "start": 1, "end": 5}}
    coverage = {"pkg.Cls.bar": ["pkg.ClsTest.testBar"]}
    report = impact_cli.build_report({"src/X.java": {3}}, methods, coverage, {},
                                     test_cmd="mvn test")
    assert "mvn test" in report and "./gradlew" not in report


# ── #4 failure attribution ────────────────────────────────────────────────────

def test_norm_key_unifies_gradle_fqn_and_dotted_forms():
    k = impact_cli._norm_key("picocli.AbbreviationMatcherTest.testAbbrevOptions")
    assert k == "abbreviationmatchertest.testabbrevoptions"
    assert impact_cli._norm_key("AbbreviationMatcherTest > testAbbrevOptions") == k
    assert impact_cli._norm_key("picocli.AbbreviationMatcherTest > testAbbrevOptions()") == k
    assert impact_cli._norm_key("AbbreviationMatcherTest.testAbbrevOptions") == k
    assert impact_cli._norm_key("noseparator") is None


def test_extract_failed_pulls_test_lines_and_skips_task_failures():
    out = impact_cli._extract_failed(
        "> Task :test\n"
        "picocli.HelpTest > testTextTable FAILED\n"
        "    java.lang.AssertionError at HelpTest.java:1\n"
        "MapOptionsOptionalTest > testMapFallback FAILED\n"
        "> Task :test FAILED\n"      # a TASK failure, not a test → must be dropped
        "BUILD FAILED in 4m 22s\n")  # doesn't end in FAILED → ignored
    assert out == ["picocli.HelpTest > testTextTable",
                   "MapOptionsOptionalTest > testMapFallback"]


def test_gather_failed_prefers_args_then_parses_stdin():
    assert impact_cli._gather_failed(["a > b"], "ignored") == ["a > b"]
    g = impact_cli._gather_failed([], "X > y FAILED\nX > y FAILED\nZ > w FAILED\n")
    assert g == ["X > y", "Z > w"]                       # parsed + deduped
    assert impact_cli._gather_failed([], "picocli.A.tA\npicocli.B.tB\n") == \
        ["picocli.A.tA", "picocli.B.tB"]                 # plain-list fallback


def test_attribute_failures_splits_caused_vs_unrelated():
    methods = {"pkg.Cls.putValue": {"file": "src/X.java", "start": 10, "end": 20}}
    coverage = {"pkg.Cls.putValue": ["picocli.HelpTest.testTextTable",
                                      "picocli.HelpTest.testPutValue"]}
    failed = ["HelpTest > testTextTable",          # covers the changed method → caused
              "picocli.OtherTest > testUnrelated"]  # not covered → unrelated
    changed, explained, unexplained = impact_cli.attribute_failures(
        failed, {"src/X.java": {12}}, methods, coverage)
    assert changed == ["pkg.Cls.putValue"]
    assert [n for n, _ in explained] == ["HelpTest > testTextTable"]
    assert unexplained == ["picocli.OtherTest > testUnrelated"]


def test_build_failures_report_formats_both_buckets():
    methods = {"pkg.Cls.putValue": {"file": "src/X.java", "start": 10, "end": 20}}
    coverage = {"pkg.Cls.putValue": ["picocli.HelpTest.testTextTable"]}
    report = impact_cli.build_failures_report(
        ["HelpTest > testTextTable", "OtherTest > testX"],
        {"src/X.java": {12}}, methods, coverage)
    assert "Caused by a method you changed (1" in report
    assert "pkg.Cls.putValue" in report                  # attributed to the method
    assert "NOT covered by your change (1" in report
