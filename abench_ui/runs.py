"""Read run artefacts + structured method comparison."""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path


class RunNotFound(Exception):
    pass


def _rundir(root_runs_dir: Path, condition: str, rep: int) -> Path:
    root = Path(root_runs_dir).resolve()
    target = (root / condition / f"rep_{rep}").resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise RunNotFound(f"invalid condition path: {condition}")
    return target


def _has_run_dirs(runs_dir: Path) -> bool:
    """A runs dir is laid out as <runs_dir>/<cond>/rep_*/... — true if any such
    rep directory exists. Structural (doesn't require metrics.json) so artefact
    endpoints resolve even for runs that only wrote e.g. a verify log."""
    for cond_dir in runs_dir.iterdir() if runs_dir.is_dir() else []:
        if not cond_dir.is_dir():
            continue
        for rep_dir in cond_dir.iterdir():
            if rep_dir.is_dir() and rep_dir.name.startswith("rep_"):
                return True
    return False


def _count_runs(runs_dir: Path) -> tuple[int, int]:
    """Return (total_runs, valid_runs) for a runs dir laid out as
    <runs_dir>/<cond>/rep_*/metrics.json. valid_runs = runs whose metrics
    carry success not None."""
    total = 0
    valid = 0
    for m_path in runs_dir.glob("*/rep_*/metrics.json"):
        if not m_path.is_file():
            continue
        total += 1
        try:
            m = json.loads(m_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if m.get("success") is not None:
            valid += 1
    return total, valid


def list_batches(exp_runs_root: Path) -> list[dict]:
    """Newest-first batches under <exp>/runs/<exp>/. A batch dir contains
    <cond>/rep_*/ run directories. If no batch dirs exist but a legacy FLAT
    layout does (<cond>/rep_*/ directly under the root), surface it as a single
    synthetic batch id 'legacy' (no files moved).

    Returns one dict per batch: {"id", "total_runs", "valid_runs"} (counts are
    metrics-based: total_runs = rep dirs with metrics.json, valid_runs = those
    whose metrics carry success not None).

    Sorted by id descending (timestamp ids sort chronologically); "legacy"
    sorts last.
    """
    root = Path(exp_runs_root)
    if not root.is_dir():
        return []

    batches: list[dict] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        # A batch dir D has grandchildren D/<cond>/rep_*/ run directories.
        if _has_run_dirs(child):
            total, valid = _count_runs(child)
            batches.append({"id": child.name, "total_runs": total, "valid_runs": valid})

    if batches:
        # Newest-first by id; only real batch dirs reach here, so a plain
        # descending sort gives chronological-newest-first for timestamp ids.
        batches.sort(key=lambda b: b["id"], reverse=True)
        return batches

    # No batch dirs — check for a legacy flat layout directly under root.
    if _has_run_dirs(root):
        total, valid = _count_runs(root)
        return [{"id": "legacy", "total_runs": total, "valid_runs": valid}]

    return []


def batch_runs_dir(exp_runs_root: Path, batch: str | None) -> Path | None:
    """Resolve the runs dir for a batch.

    None/'' -> newest batch (or flat root if legacy).
    'legacy' -> the flat root.
    Otherwise <root>/<batch>.

    Returns None if the resolved dir doesn't exist / has no runs.
    """
    root = Path(exp_runs_root)
    batches = list_batches(root)
    if not batches:
        return None

    if not batch:
        # Newest by default — list_batches already sorted newest-first.
        top = batches[0]["id"]
        return root if top == "legacy" else root / top

    if batch == "legacy":
        # Only valid if the root actually has a flat layout.
        if any(b["id"] == "legacy" for b in batches):
            return root
        return None

    # Path-traversal guard: a batch id must resolve to a direct child of root.
    target = (root / batch).resolve()
    try:
        if target.parent != root.resolve():
            return None
    except OSError:
        return None
    if any(b["id"] == batch for b in batches):
        return root / batch
    return None


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
                "duration_s": m.get("duration_s"),
                "n_steps": m.get("n_steps"),
                "n_tool_calls": m.get("n_tool_calls"),
                "n_test_runs": m.get("n_test_runs"),
                "cost": m.get("cost"),
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
    regen_file_override: "Path | None" = None,
) -> dict:
    """Extract a named method/function from reference and workdir versions of
    target_file, returning the lines for each + an equivalence flag.

    If regen_file_override is given, it is used in place of workdir/target_file
    as the regenerated content (e.g. a target_after_agent.txt snapshot).

    Supports Python via ast and Java via brace-balancing on a regex'd signature."""
    ref_text = (Path(reference_dir) / target_file).read_text()
    if regen_file_override is not None:
        regen_text = Path(regen_file_override).read_text()
    else:
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
