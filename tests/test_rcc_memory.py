# tests/test_rcc_memory.py
from abench.rcc_memory import RccMemory


def test_roundtrip_and_persistence(tmp_path):
    p = tmp_path / "mem" / "rcc-memory.json"
    m = RccMemory(p)
    assert m.get("p.C.putValue") is None
    m.put("p.C.putValue", {"nodes": [], "edges": []}, ["p.T1"])
    e = m.get("p.C.putValue")
    assert e["causal_graph"] == {"nodes": [], "edges": []}
    assert e["test_classes"] == ["p.T1"]
    assert e["ts"] > 0
    # a fresh instance reads the same file
    assert RccMemory(p).get("p.C.putValue")["test_classes"] == ["p.T1"]


def test_invalidate_removes_and_persists(tmp_path):
    p = tmp_path / "m.json"
    m = RccMemory(p)
    m.put("a", {}, [])
    m.invalidate("a")
    assert m.get("a") is None
    assert RccMemory(p).get("a") is None
    m.invalidate("never-there")            # no-op, no crash


def test_corrupt_or_missing_file_is_empty(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    assert RccMemory(p).get("x") is None
    p2 = tmp_path / "list.json"
    p2.write_text("[1,2]")
    assert RccMemory(p2).get("x") is None
