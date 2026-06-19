"""Read run artefacts + structured method comparison."""
from __future__ import annotations

import json
from pathlib import Path

from abench.methods import method_lines, normalised

# Batch-layout helpers live in core abench/ so abench.reverify can resolve a
# batch dir without importing abench_ui. Re-exported here so the server +
# existing tests keep importing them from abench_ui.runs unchanged.
from abench.run_layout import (  # noqa: F401
    batch_runs_dir,
    list_batches,
)


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
                # killed by the loop watchdog; fall back to interrupted_reason
                # for metrics.json written before the `stuck` field existed.
                "stuck": bool(m.get("stuck")
                              or m.get("interrupted_reason") == "looping"),
                "stop_reason": m.get("stop_reason"),
                "verify_status": m.get("verify_status"),
                "success": m.get("success"),
                "duration_s": m.get("duration_s"),
                "n_steps": m.get("n_steps"),
                "n_tool_calls": m.get("n_tool_calls"),
                "n_test_runs": m.get("n_test_runs"),
                "n_tests_executed": m.get("n_tests_executed"),
                "tests_pass_rate": m.get("tests_pass_rate"),
                "verify_passed_count": m.get("verify_passed_count"),
                "verify_failed_count": m.get("verify_failed_count"),
                "cost": m.get("cost"),
                "tokens_in": m.get("tokens_in"),
                "tokens_out": m.get("tokens_out"),
                "tokens_reasoning": m.get("tokens_reasoning"),
                "n_reads": m.get("n_reads"),
                "n_searches": m.get("n_searches"),
                "n_files_edited": m.get("n_files_edited"),
                "tool_calls_by_name": m.get("tool_calls_by_name"),
                "obs_tokens_total": m.get("obs_tokens_total"),
                "obs_tokens_by_tool": m.get("obs_tokens_by_tool"),
                "n_service_errors": m.get("n_service_errors", 0),
                "made_source_changes": m.get("made_source_changes", False),
                "verify_insensitive": m.get("verify_insensitive", False),
                "cheating": m.get("cheating"),
                "started_at": _mtime_iso(m_path),
            })
    return items


def cost_summary(experiments_dir: Path) -> dict:
    """Total $ spend across EVERY run of EVERY experiment — sum of each run's
    metrics.json `cost`, over all batches (and the legacy flat layout).

    Returns {total_cost, n_runs, n_runs_with_cost, by_experiment}. A run whose
    cost is missing/None (e.g. a free model) is counted in n_runs but not priced.
    Best-effort: an unreadable metrics.json is skipped, not fatal."""
    experiments_dir = Path(experiments_dir)
    total = 0.0
    n_runs = 0
    n_with_cost = 0
    by_exp: dict[str, float] = {}
    for m_path in sorted(experiments_dir.glob("*/runs/**/metrics.json")):
        try:
            m = json.loads(m_path.read_text())
        except (OSError, ValueError):
            continue
        n_runs += 1
        exp_name = m_path.relative_to(experiments_dir).parts[0]
        by_exp.setdefault(exp_name, 0.0)
        cost = m.get("cost")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            total += float(cost)
            n_with_cost += 1
            by_exp[exp_name] += float(cost)
    return {
        "total_cost": round(total, 4),
        "n_runs": n_runs,
        "n_runs_with_cost": n_with_cost,
        "by_experiment": {k: round(v, 4) for k, v in by_exp.items()},
    }


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
    original = method_lines(ref_text, target_file, method_name)
    regen = method_lines(regen_text, target_file, method_name)
    return {
        "method_name": method_name,
        "original_lines": original,
        "regen_lines": regen,
        "equivalent": normalised(original) == normalised(regen),
    }


def _mtime_iso(p: Path) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(p.stat().st_mtime).isoformat()
