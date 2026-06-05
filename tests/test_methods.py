"""Method extraction + similarity (shared by /method_comparison + cheating)."""
from abench.methods import (
    best_method_similarity, extract_java_method, method_similarity,
)

_JAVA_REF = """\
class C {
    public int putValue(int row, int col) {
        if (row > rowCount) { throw new IllegalArgumentException("x"); }
        return row + col;
    }
    public void other() {}
}
"""

_JAVA_SAME = _JAVA_REF.replace("    ", "  ")  # same body, different indentation
_JAVA_DIFF = """\
class C {
    public int putValue(int row, int col) {
        return 0;  // totally different body
    }
}
"""


def test_extract_java_method_balances_braces():
    body = extract_java_method(_JAVA_REF, "putValue")
    assert body[0].strip().startswith("public int putValue")
    assert body[-1].strip() == "}"
    assert any("IllegalArgumentException" in ln for ln in body)


def test_similarity_identical_ignores_whitespace():
    assert method_similarity(_JAVA_REF, _JAVA_SAME, "X.java", "putValue") == 1.0


def test_similarity_low_for_different_body():
    assert method_similarity(_JAVA_REF, _JAVA_DIFF, "X.java", "putValue") < 0.8


def test_similarity_none_when_method_missing():
    assert method_similarity(_JAVA_REF, _JAVA_DIFF, "X.java", "nope") is None


def test_best_method_similarity_takes_max():
    # one matching method (1.0) + one missing (None) → 1.0
    assert best_method_similarity(
        _JAVA_REF, _JAVA_SAME, "X.java", ["nope", "putValue"]) == 1.0
    assert best_method_similarity(_JAVA_REF, _JAVA_SAME, "X.java", ["nope"]) is None
