# experiments/picocli-putValue/tests/test_strip_target.py
import subprocess
import sys
from pathlib import Path
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "strip_target.py"
SRC = """class A {
    public int keep() { return 1; }
    public Cell putValue(int row, int col, Text value) {
        if (row > 0) { throw new X(); }
        return new Cell(col, row);
    }
}
"""

def run_strip(tmp_path, sig="public Cell putValue(int row, int col, Text value)"):
    f = tmp_path / "A.java"
    f.write_text(SRC)
    return subprocess.run([sys.executable, SCRIPT, "--file", f, "--signature", sig,
                           "--stub", 'throw new UnsupportedOperationException("TODO");'],
                          capture_output=True, text=True), f

def test_strips_only_target_body(tmp_path):
    r, f = run_strip(tmp_path)
    assert r.returncode == 0, r.stderr
    out = f.read_text()
    assert 'throw new UnsupportedOperationException("TODO");' in out
    assert "return new Cell(col, row);" not in out
    assert "public int keep() { return 1; }" in out

def test_signature_not_found_fails(tmp_path):
    r, _ = run_strip(tmp_path, sig="public void nope()")
    assert r.returncode != 0 and "not found" in r.stderr
