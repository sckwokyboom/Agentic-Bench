from pathlib import Path

from abench.augcheck import detect_format, render

FIX = Path(__file__).parent / "fixtures" / "runtime"


def test_detect_format():
    assert detect_format(FIX / "chain-putValue.jsonl") == "chain"
    assert detect_format(FIX / "single-putValue.jsonl") == "single"
    assert detect_format(FIX / "does-not-exist.jsonl") == "empty"


def test_render_chain_fixture_matches_expectations():
    card = render(FIX / "chain-putValue.jsonl", "TextTable.putValue")
    assert "RUNTIME CHAIN for TextTable.putValue" in card
    # call path renders outer -> target
    assert card.index("CommandLine.usage(") < card.index("TextTable.putValue(0")
    # per-frame runtime args are READABLE (summarizer), not Type@hash
    assert "Text[2]{" in card and "@" not in card.split("Text[2]{")[1].split("}")[0]
    # per-frame outcome: the target's return value surfaced
    assert "Cell[column=0, row=0]" in card
    # evidence-not-fix framing
    assert "do not curve-fit" in card and "fix by" not in card.lower()


def test_render_single_fixture_matches_expectations():
    card = render(FIX / "single-putValue.jsonl", "TextTable.putValue")
    assert "RUNTIME EVIDENCE for TextTable.putValue" in card
    assert "putValue:17415" in card and "HelpTest.testCatUsageFormat" in card
    assert "UnsupportedOperationException" in card
    assert "org.junit" not in card                 # framework frames trimmed from the corridor


def test_render_missing_capture_is_graceful():
    assert "no capture" in render(FIX / "nope.jsonl", "x")
