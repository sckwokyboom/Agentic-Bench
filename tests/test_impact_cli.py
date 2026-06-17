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
