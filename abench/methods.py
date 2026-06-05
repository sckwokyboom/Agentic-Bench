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


def method_similarity(
    ref_text: str, regen_text: str, target_file: str, name: str,
) -> float | None:
    """0..1 similarity of one method's body between two files (whitespace-
    normalised difflib ratio). None if the method isn't found in BOTH files."""
    a = normalised(method_lines(ref_text, target_file, name))
    b = normalised(method_lines(regen_text, target_file, name))
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
