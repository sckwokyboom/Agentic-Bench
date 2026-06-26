from abench.runtime_chain import parse_chain, build_chain_card

# Realistic chain-mode capture (Recorder JSONL): one corridor dump (target-first)
# + per-activation exit events (ret/throw), keyed by `act`.
_SAMPLE = (
    '{"target":"picocli.CommandLine$Help$TextTable.putValue","corridor":['
    '{"act":3,"method":"picocli.CommandLine$Help$TextTable.putValue","args":["0","0",""]},'
    '{"act":2,"method":"picocli.CommandLine$Help$TextTable.addRowValues","args":["Text[2]{-c, --count}"]},'
    '{"act":1,"method":"picocli.CommandLine.usage","args":["PrintStream","OFF"]}]}\n'
    '{"act":3,"method":"picocli.CommandLine$Help$TextTable.putValue","exit":true,'
    '"throw":"java.lang.UnsupportedOperationException: TODO: implement putValue"}\n'
    '{"act":2,"method":"picocli.CommandLine$Help$TextTable.addRowValues","exit":true,"ret":"Cell[0,1]"}\n'
    '{"act":1,"method":"picocli.CommandLine.usage","exit":true,"ret":"void"}\n'
)


def test_parse_chain(tmp_path):
    f = tmp_path / "cap.jsonl"
    f.write_text(_SAMPLE)
    corridors, exits = parse_chain(f)
    assert len(corridors) == 1
    c = corridors[0]
    assert c.target.endswith("putValue")
    assert [fr["method"].rsplit(".", 1)[-1] for fr in c.frames] == ["putValue", "addRowValues", "usage"]
    assert c.frames[0]["args"] == ["0", "0", ""]
    assert exits[3]["throw"].startswith("java.lang.UnsupportedOperationException")
    assert exits[2]["ret"] == "Cell[0,1]"


def test_parse_chain_tolerant(tmp_path):
    f = tmp_path / "cap.jsonl"
    f.write_text("garbage\n{}\n\n")
    assert parse_chain(f) == ([], {})
    assert parse_chain(tmp_path / "missing.jsonl") == ([], {})


def test_build_chain_card_renders_path_args_and_outcomes(tmp_path):
    f = tmp_path / "cap.jsonl"
    f.write_text(_SAMPLE)
    corridors, exits = parse_chain(f)
    card = build_chain_card(corridors, exits, "TextTable.putValue")
    assert card is not None
    assert "RUNTIME CHAIN for TextTable.putValue" in card
    # rendered outer -> target (the call descending in): the usage FRAME precedes
    # the putValue FRAME (compare the frame renderings, not the header label)
    assert card.index("CommandLine.usage(") < card.index("TextTable.putValue(0")
    # short method names + per-frame runtime args
    assert "TextTable.putValue(0, 0, (empty))" in card
    assert "addRowValues(Text[2]{-c, --count})" in card
    assert "CommandLine.usage(PrintStream, OFF)" in card
    # per-frame outcomes: enclosing return + the target throw
    assert "Cell[0,1]" in card
    assert "throws java.lang.UnsupportedOperationException" in card
    assert "do not curve-fit" in card
    assert "fix by" not in card.lower()


def test_build_chain_card_none_when_empty():
    assert build_chain_card([], {}, "TextTable.putValue") is None
