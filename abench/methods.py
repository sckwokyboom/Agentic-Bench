"""Extract a named method/function body from source + compare two bodies.

Shared by the /method_comparison endpoint and the cheating detector's
'output ≈ original' signal. Pure, no I/O. Python via ast, Java via
brace-balancing on a regex'd signature; otherwise the whole file.
"""
from __future__ import annotations

import ast
import difflib
import re

_JAVA_SIG = re.compile(
    r"(?:public|private|protected|static|final|synchronized|abstract|\s)*\s*"
    r"[\w<>\[\],\s]*\s+(?P<name>\w+)\s*\([^)]*\)\s*(?:throws\s+[\w.,\s]+)?\s*\{"
)


def extract_py_function(source: str, name: str) -> list[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    lines = source.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return lines[node.lineno - 1: node.end_lineno]
    return []


def extract_java_method(source: str, name: str) -> list[str]:
    lines = source.splitlines()
    for i, line in enumerate(lines):
        # Cheap pre-filter: a signature line for `name` must contain `name`, so
        # skip the rest. This avoids running _JAVA_SIG (which backtracks badly on
        # long lines) on every line of a large file — extracting putValue from
        # the 19k-line CommandLine.java drops from ~36s to milliseconds.
        if name not in line:
            continue
        m = _JAVA_SIG.search(line)
        if m and m.group("name") == name:
            depth = line.count("{") - line.count("}")
            end = i
            for j in range(i + 1, len(lines)):
                depth += lines[j].count("{") - lines[j].count("}")
                end = j
                if depth == 0:
                    break
            return lines[i: end + 1]
    return []


def method_lines(source: str, target_file: str, name: str) -> list[str]:
    if target_file.endswith(".py"):
        return extract_py_function(source, name)
    if target_file.endswith(".java"):
        return extract_java_method(source, name)
    return source.splitlines()


def normalised(lines: list[str]) -> str:
    """Whitespace-insensitive form: strip each line, drop blanks, join."""
    return "\n".join(line.strip() for line in lines if line.strip())


_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_C_LIKE = (".java", ".kt", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs",
           ".c", ".cc", ".cpp", ".h", ".hpp", ".scala", ".cs", ".swift")


def _strip_comments(text: str, target_file: str) -> str:
    """Drop comments so a copy with an added/removed comment still compares as
    near-identical. Heuristic (regex, not a real lexer) — fine for a similarity
    ratio since BOTH bodies get the exact same treatment."""
    if target_file.endswith(_C_LIKE):
        text = _BLOCK_COMMENT.sub("", text)
        text = re.sub(r"//.*?$", "", text, flags=re.M)
    elif target_file.endswith(".py"):
        text = re.sub(r"#.*?$", "", text, flags=re.M)
    return text


def code_normalised(lines: list[str], target_file: str) -> str:
    """Comment- AND format-insensitive form of a body: strip comments, then
    collapse every run of whitespace (incl. newlines/indentation) to one space.
    So a copy that was reindented, reflowed onto other lines, or had a comment
    added still normalises to the same string as the original."""
    text = _strip_comments("\n".join(lines), target_file)
    return re.sub(r"\s+", " ", text).strip()


def method_similarity(
    ref_text: str, regen_text: str, target_file: str, name: str,
) -> float | None:
    """0..1 similarity of one method's body between two files (comment- and
    format-insensitive difflib ratio, so trivial reformatting/comments don't
    hide a copy). None if the method isn't found in BOTH files. 1.0 means the
    bodies are identical modulo comments and whitespace."""
    a = code_normalised(method_lines(ref_text, target_file, name), target_file)
    b = code_normalised(method_lines(regen_text, target_file, name), target_file)
    if not a or not b:
        return None
    return difflib.SequenceMatcher(None, a, b).ratio()


def best_method_similarity(
    ref_text: str, regen_text: str, target_file: str, names: list[str] | None,
) -> float | None:
    """Max method_similarity across names (the most-suspicious match), or None
    if none of the methods are comparable in both files."""
    sims = []
    for n in names or []:
        s = method_similarity(ref_text, regen_text, target_file, n)
        if s is not None:
            sims.append(s)
    return max(sims) if sims else None
