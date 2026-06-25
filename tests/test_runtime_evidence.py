from abench.runtime_evidence import (
    parse_capture, trim_corridor, build_card, CaptureEvent,
)

_REAL = (
    '{"method":"picocli.CommandLine$Help$TextTable.putValue","args":["0","0",""],'
    '"stack":["picocli.CommandLine$Help$TextTable.putValue:17415",'
    '"picocli.CommandLine$Help$TextTable.addRowValues:17380",'
    '"picocli.CommandLine$Help.join:16325","picocli.CommandLine.usage:2795",'
    '"picocli.HelpTest.testCatUsageFormat:2331","org.junit.runners.model.X.run:1"]}\n'
    '{"method":"picocli.CommandLine$Help$TextTable.putValue","exit":true,'
    '"throw":"java.lang.UnsupportedOperationException: TODO: implement putValue"}\n'
)


def test_parse_capture(tmp_path):
    f = tmp_path / "cap.jsonl"
    f.write_text(_REAL)
    events = parse_capture(f)
    assert len(events) == 2
    enter = events[0]
    assert enter.method.endswith("putValue") and enter.args == ["0", "0", ""]
    assert enter.exit is False and enter.thrown is None
    assert events[1].exit is True
    assert "UnsupportedOperationException" in events[1].thrown


def test_parse_capture_tolerant(tmp_path):
    f = tmp_path / "cap.jsonl"
    f.write_text('not json\n{"no":"method"}\n\n')
    assert parse_capture(f) == []
    assert parse_capture(tmp_path / "missing.jsonl") == []   # absent file -> []


def test_trim_corridor_drops_framework_frames():
    stack = ["picocli.CommandLine$Help$TextTable.putValue:17415",
             "picocli.CommandLine.usage:2795",
             "picocli.HelpTest.testCatUsageFormat:2331",
             "org.junit.runners.model.X.run:1",
             "jdk.internal.reflect.Y.invoke:1"]
    out = trim_corridor(stack)
    assert out[0].endswith("putValue:17415")
    assert any("HelpTest.testCatUsageFormat" in f for f in out)   # test frame kept
    assert all("org.junit" not in f and "jdk." not in f for f in out)


def test_build_card_dedups_and_caps(tmp_path):
    f = tmp_path / "cap.jsonl"
    f.write_text(_REAL + _REAL)   # duplicate call
    events = parse_capture(f)
    card = build_card(events, "TextTable.putValue", max_examples=3)
    assert card is not None
    assert "RUNTIME EVIDENCE for TextTable.putValue" in card
    assert card.count("args:") == 1                       # duplicate (corridor,args) deduped
    assert "0, 0, (empty)" in card                        # args rendered
    assert "corridor:" in card and "putValue:17415" in card
    assert "HelpTest.testCatUsageFormat" in card          # test frame in corridor
    assert "UnsupportedOperationException" in card        # throw surfaced
    assert "do not curve-fit" in card                     # evidence-not-fix framing
    assert "fix by" not in card.lower()                   # never prescribes a fix


def test_build_card_none_when_empty():
    assert build_card([], "TextTable.putValue") is None
