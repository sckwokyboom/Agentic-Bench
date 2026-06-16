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


def test_extract_java_method_ignores_earlier_call_of_same_name():
    """A call (or comment) mentioning the name before the definition must not
    derail extraction — guards the name pre-filter + the brace-requiring
    signature match."""
    src = (
        "class C {\n"
        "    void caller() { obj.putValue(1, 2); }   // a call, not the def\n"
        "    public int putValue(int row, int col) {\n"
        "        return row + col;\n"
        "    }\n"
        "}\n"
    )
    body = extract_java_method(src, "putValue")
    assert body[0].strip().startswith("public int putValue")
    assert body[-1].strip() == "}"
    assert any("return row + col" in ln for ln in body)


def test_similarity_identical_ignores_whitespace():
    assert method_similarity(_JAVA_REF, _JAVA_SAME, "X.java", "putValue") == 1.0


def test_similarity_low_for_different_body():
    assert method_similarity(_JAVA_REF, _JAVA_DIFF, "X.java", "putValue") < 0.8


_JAVA_REFORMATTED_WITH_COMMENT = """\
class C {
    public int putValue(int row, int col) {
        // recompute the cell value
        if (row > rowCount) {
            throw new IllegalArgumentException("x");
        }
        return row + col;
    }
}
"""


def test_similarity_ignores_comments_and_reformatting():
    """A body reflowed onto more lines with an extra comment is still a verbatim
    copy → 1.0 (the old whitespace-only normaliser scored this below 1.0)."""
    assert method_similarity(
        _JAVA_REF, _JAVA_REFORMATTED_WITH_COMMENT, "X.java", "putValue") == 1.0


_PY_REF = "def f(x):\n    return x + 1\n"
_PY_COMMENTED = "def f(x):\n    # add one\n    return x + 1  # trivial\n"


def test_similarity_ignores_python_comments():
    assert method_similarity(_PY_REF, _PY_COMMENTED, "m.py", "f") == 1.0


def test_similarity_none_when_method_missing():
    assert method_similarity(_JAVA_REF, _JAVA_DIFF, "X.java", "nope") is None


def test_best_method_similarity_takes_max():
    # one matching method (1.0) + one missing (None) → 1.0
    assert best_method_similarity(
        _JAVA_REF, _JAVA_SAME, "X.java", ["nope", "putValue"]) == 1.0
    assert best_method_similarity(_JAVA_REF, _JAVA_SAME, "X.java", ["nope"]) is None
