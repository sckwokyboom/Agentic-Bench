"""Read run artefacts + structured method comparison."""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path


class RunNotFound(Exception):
    pass


def _rundir(root_runs_dir: Path, condition: str, rep: int) -> Path:
    return Path(root_runs_dir) / condition / f"rep_{rep}"


def list_runs(root_runs_dir: Path) -> list[dict]:
    """Walk runs/<exp>/<cond>/<rep>/ and return summaries."""
    root = Path(root_runs_dir)
    items: list[dict] = []
    if not root.is_dir():
        return items
    for cond_dir in sorted(root.iterdir()):
        if not cond_dir.is_dir():
            continue
        for rep_dir in sorted(cond_dir.iterdir()):
            if not rep_dir.is_dir() or not rep_dir.name.startswith("rep_"):
                continue
            m_path = rep_dir / "metrics.json"
            if not m_path.is_file():
                continue
            m = json.loads(m_path.read_text())
            items.append({
                "condition": cond_dir.name,
                "rep": int(rep_dir.name.removeprefix("rep_")),
                "finished": m.get("finished"),
                "interrupted_reason": m.get("interrupted_reason"),
                "verify_status": m.get("verify_status"),
                "success": m.get("success"),
                "started_at": _mtime_iso(m_path),
            })
    return items


def read_artefact(root_runs_dir: Path, condition: str, rep: int, name: str) -> str:
    """Return the raw file contents of <runs>/<cond>/rep_N/<name>."""
    rd = _rundir(root_runs_dir, condition, rep)
    p = rd / name
    if not p.is_file():
        raise RunNotFound(f"{condition}/rep_{rep}/{name}")
    return p.read_text(encoding="utf-8")


def patch_success(root_runs_dir: Path, condition: str, rep: int, *, success: bool | None) -> dict:
    """Update metrics.json[success] in place."""
    rd = _rundir(root_runs_dir, condition, rep)
    m_path = rd / "metrics.json"
    if not m_path.is_file():
        raise RunNotFound(f"{condition}/rep_{rep}/metrics.json")
    metrics = json.loads(m_path.read_text())
    metrics["success"] = success
    m_path.write_text(json.dumps(metrics, indent=2))
    return metrics


def method_comparison(
    *, reference_dir: Path, workdir: Path,
    target_file: str, method_name: str,
) -> dict:
    """Extract a named method/function from reference and workdir versions of
    target_file, returning the lines for each + an equivalence flag.

    Supports Python via ast and Java via brace-balancing on a regex'd signature."""
    ref_text = (Path(reference_dir) / target_file).read_text()
    regen_text = (Path(workdir) / target_file).read_text()
    if target_file.endswith(".py"):
        original = _extract_py_function(ref_text, method_name)
        regen = _extract_py_function(regen_text, method_name)
    elif target_file.endswith(".java"):
        original = _extract_java_method(ref_text, method_name)
        regen = _extract_java_method(regen_text, method_name)
    else:
        original, regen = ref_text.splitlines(), regen_text.splitlines()
    equivalent = _normalised(original) == _normalised(regen)
    return {
        "method_name": method_name,
        "original_lines": original,
        "regen_lines": regen,
        "equivalent": equivalent,
    }


def _extract_py_function(source: str, name: str) -> list[str]:
    tree = ast.parse(source)
    lines = source.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            start = node.lineno - 1
            end = node.end_lineno
            return lines[start:end]
    return []


_JAVA_SIG = re.compile(
    r"(?:public|private|protected|static|final|synchronized|abstract|\s)*\s*"
    r"[\w<>\[\],\s]*\s+(?P<name>\w+)\s*\([^)]*\)\s*(?:throws\s+[\w.,\s]+)?\s*\{"
)


def _extract_java_method(source: str, name: str) -> list[str]:
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
            return lines[i:end + 1]
    return []


def _normalised(lines: list[str]) -> str:
    return "\n".join(line.strip() for line in lines if line.strip())


def _mtime_iso(p: Path) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(p.stat().st_mtime).isoformat()
