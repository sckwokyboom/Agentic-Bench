# tests/test_rcc_adapters.py
from abench.orchestration_adapters import collect_probe_lines, subset_command


def test_subset_command_gradle_appends_class_filters():
    cmd = subset_command("gradle test --continue", ["p.CT", "p.OtherTest"])
    assert cmd == 'gradle test --continue --tests "p.CT" --tests "p.OtherTest"'


def test_subset_command_maven_uses_dtest():
    cmd = subset_command("mvn -q test", ["p.CT", "p.DT"])
    assert "-Dtest=p.CT,p.DT" in cmd and "-DfailIfNoTests=false" in cmd


def test_subset_command_unknown_or_empty_returns_base():
    assert subset_command("make check", ["p.CT"]) == "make check"
    assert subset_command("gradle test", []) == "gradle test"


def test_collect_probe_lines_from_stdout_and_junit_xml(tmp_path):
    xml_dir = tmp_path / "build" / "test-results" / "test"
    xml_dir.mkdir(parents=True)
    (xml_dir / "TEST-p.CT.xml").write_text(
        '<testsuite name="p.CT" tests="1" failures="0">'
        "<system-out>noise\nRCC_PROBE C.putValue: ret=null\n</system-out>"
        "</testsuite>")
    out = "gradle noise\nRCC_PROBE C.getValue: ret=null\nRCC_PROBE C.putValue: ret=null\n"
    lines = collect_probe_lines(tmp_path, out)
    # deduped, order: stdout scanned first, then the XML
    assert lines == ["RCC_PROBE C.getValue: ret=null",
                     "RCC_PROBE C.putValue: ret=null"]


def test_collect_probe_lines_caps(tmp_path):
    out = "\n".join(f"RCC_PROBE m: v={i}" for i in range(500))
    assert len(collect_probe_lines(tmp_path, out, max_lines=300)) == 300
