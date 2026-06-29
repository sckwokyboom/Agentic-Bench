# abench/report.py
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

NUMERIC = [
    "duration_s", "n_steps", "n_tool_calls", "n_test_runs", "n_tests_executed",
    "n_reads", "n_searches", "n_files_edited", "diff_lines_added", "diff_lines_removed",
    "tokens_in", "tokens_out", "tokens_reasoning", "cache_read", "cache_write",
    "cost", "time_to_first_edit_s",
    "n_service_errors", "n_rate_limits",
]


def _rep_from_dirname(name: str) -> int:
    """Parse the rep index from a ``rep_<n>`` dir name; 0 if not parseable."""
    suffix = name[4:] if name.startswith("rep_") else name
    return int(suffix) if suffix.isdigit() else 0


def _valid_runs(df: pd.DataFrame) -> pd.DataFrame:
    """Runs that count toward the comparison. Excludes:
      - interrupted runs (cancelled / looping / timeout), and
      - infra/crash runs that never measured the agent: a service error
        (`n_service_errors > 0`) or zero steps (`n_steps == 0`, e.g. opencode
        failed to launch — the `augmented-tool rep0` case). These would otherwise
        be scored as a spurious agent failure and drag the efficiency means.
    Invalid-verify (undercount) runs are KEPT here — their step/time/cost effort is
    real — but are excluded from the pass-rate SUM (their verdict is unusable)."""
    m = df["interrupted_reason"].isna()
    if "n_service_errors" in df.columns:
        m = m & (df["n_service_errors"].fillna(0) == 0)
    if "n_steps" in df.columns:
        # Exclude only an EXPLICIT zero-step run (opencode never produced a step —
        # a crash). A MISSING value is unknown, not a crash, so keep it.
        m = m & ~(df["n_steps"].notna() & (df["n_steps"] == 0))
    return df[m]


def load_runs(root: Path) -> pd.DataFrame:
    rows = []
    for metrics_file in sorted(Path(root).glob("*/*/metrics.json")):
        try:
            metrics = json.loads(metrics_file.read_text())
        except (OSError, ValueError):
            # Partial/aborted run with an unreadable metrics.json — skip it
            # rather than 500 the whole summary.
            continue
        # manifest.json may be missing (run interrupted before it was written —
        # it is the last artefact _run_one writes) or unparseable. Fall back to
        # the on-disk path for condition/rep so a partial run never crashes.
        rundir = metrics_file.parent
        manifest: dict = {}
        manifest_file = rundir / "manifest.json"
        if manifest_file.is_file():
            try:
                manifest = json.loads(manifest_file.read_text())
            except (OSError, ValueError):
                manifest = {}
        condition = manifest.get("condition") or rundir.parent.name
        rep = manifest.get("rep")
        if rep is None:
            rep = _rep_from_dirname(rundir.name)
        row = {"condition": condition, "rep": rep}
        row.update({k: metrics.get(k) for k in NUMERIC})
        row["finished"] = metrics.get("finished")
        row["interrupted_reason"] = metrics.get("interrupted_reason")
        row["success"] = metrics.get("success")
        row["tests_pass_rate"] = metrics.get("tests_pass_rate")
        # Stable, long-existing verify counts — the condition-level pass rate is
        # aggregated from these (Σpassed/Σtotal), NOT from the derived per-run
        # tests_pass_rate, so runs written before that field existed still count.
        row["verify_passed_count"] = metrics.get("verify_passed_count")
        row["verify_failed_count"] = metrics.get("verify_failed_count")
        row["verify_expected_total"] = metrics.get("verify_expected_total")
        # Hygiene columns: verdict + how many tests actually ran + did it compile —
        # so an undercount (executed_total ≪ expected) and crashes are visible.
        row["verify_status"] = metrics.get("verify_status")
        row["executed_total"] = metrics.get("executed_total")
        row["compiled"] = metrics.get("compiled")
        rows.append(row)
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    valid = _valid_runs(df)
    return valid.groupby("condition")[NUMERIC].agg(["mean", "median", "std"])


def summary_json(root: Path) -> dict:
    """JSON-friendly aggregate for the Web UI. Reuses load_runs; means/medians
    per condition over valid runs (interrupted excluded), plus augmented-vs-
    baseline percent deltas. NaN -> None; numpy scalars -> native floats."""
    df = load_runs(Path(root))
    if df.empty:
        return {"conditions": [], "deltas": {}, "total_runs": 0, "valid_runs": 0,
                "crashed_runs": 0}

    valid = _valid_runs(df)
    total_runs = int(len(df))
    valid_runs = int(len(valid))
    # Infra/crash runs (service error or 0 steps) that aren't interrupted — surfaced
    # so a dropped crash never looks like a silent agent failure.
    interrupted_runs = int(df["interrupted_reason"].notna().sum())
    crashed_runs = total_runs - valid_runs - interrupted_runs
    if valid.empty:
        return {"conditions": [], "deltas": {}, "total_runs": total_runs,
                "valid_runs": valid_runs, "crashed_runs": crashed_runs}

    mean = valid.groupby("condition")[NUMERIC].mean()
    median = valid.groupby("condition")[NUMERIC].median()

    # Per-condition count of runs the loop watchdog killed (agent looping),
    # from the FULL df — `valid` excludes interrupted runs, so a condition whose
    # every run looped still surfaces its stuck count (and its row) below.
    stuck_by_cond = (df[df["interrupted_reason"] == "looping"]
                     .groupby("condition").size())

    conditions = []
    # Iterate ALL conditions, not only those with valid runs, so an all-stuck
    # condition (e.g. a loop-prone model) does not silently vanish.
    for cond in sorted(df["condition"].unique()):
        stuck = int(stuck_by_cond.get(cond, 0))
        if cond not in mean.index:
            conditions.append({
                "name": str(cond), "runs": 0, "stuck": stuck,
                "success_rate": None, "tests_pass_rate": None, "metrics": {},
            })
            continue
        sub = valid[valid["condition"] == cond]
        succ = sub["success"].dropna()
        success_rate = (
            float((succ == True).sum()) / len(succ) if len(succ) else None  # noqa: E712
        )
        # Fraction of tests passing at the end across the condition's runs,
        # computed from SUMMED verify counts (Σpassed / Σ(passed+failed)) rather
        # than averaging the derived per-run tests_pass_rate. This keeps failing
        # runs in the denominator (a run that fails 2/2200 pulls the rate below
        # 100%) and, crucially, does NOT silently drop runs whose metrics predate
        # the tests_pass_rate field — they still carry verify_*_count. Surfaces
        # "2198/2200" near-misses the binary success rate hides.
        tot_pass = tot_total = 0.0
        have_counts = False
        if {"verify_passed_count", "verify_failed_count"} <= set(sub.columns):
            expected_col = (sub["verify_expected_total"]
                            if "verify_expected_total" in sub.columns else [None] * len(sub))
            status_col = (sub["verify_status"]
                          if "verify_status" in sub.columns else [None] * len(sub))
            for p, f, e, st in zip(sub["verify_passed_count"], sub["verify_failed_count"],
                                   expected_col, status_col):
                if st == "invalid":
                    continue  # undercount: verdict unusable → keep out of the pass rate
                if pd.notna(p) and pd.notna(f) and (p + f) > 0:
                    # Denominator is the full expected suite when known, so tests
                    # that never ran in a failing run count as not-passed.
                    run_total = float(p) + float(f)
                    if e is not None and pd.notna(e) and float(e) > run_total:
                        run_total = float(e)
                    tot_pass += float(p)
                    tot_total += run_total
                    have_counts = True
        tests_pass_rate = (tot_pass / tot_total) if have_counts and tot_total else None
        metrics = {}
        for m in NUMERIC:
            mv = mean.loc[cond, m]
            dv = median.loc[cond, m]
            metrics[m] = {
                "mean": None if pd.isna(mv) else float(mv),
                "median": None if pd.isna(dv) else float(dv),
            }
        conditions.append({
            "name": str(cond),
            "runs": int(len(sub)),
            "stuck": stuck,
            "success_rate": success_rate,
            "tests_pass_rate": tests_pass_rate,
            "metrics": metrics,
        })

    deltas: dict[str, float] = {}
    names = list(mean.index)
    if "baseline" in names and "augmented" in names:
        for m in NUMERIC:
            base = mean.loc["baseline", m]
            aug = mean.loc["augmented", m]
            if not pd.isna(base) and not pd.isna(aug) and base != 0:
                deltas[m] = round(float((aug - base) / base * 100), 1)

    return {
        "conditions": conditions,
        "deltas": deltas,
        "total_runs": total_runs,
        "valid_runs": valid_runs,
        "crashed_runs": crashed_runs,
    }


def _to_markdown(df: pd.DataFrame) -> str:
    valid = _valid_runs(df)
    means = valid.groupby("condition")[NUMERIC].mean()
    conditions = list(means.index)

    lines = [
        "# Summary",
        "",
        f"Total runs: {len(df)} (valid: {len(valid)}) | "
        f"conditions: {', '.join(conditions)}",
        "",
        "## Mean per condition (valid runs only)",
        "",
        "| metric | " + " | ".join(conditions) + " | delta (aug vs base) |",
        "|" + "---|" * (len(conditions) + 2),
    ]
    for metric in NUMERIC:
        cells = []
        for cond in conditions:
            value = means.loc[cond, metric]
            cells.append("" if pd.isna(value) else f"{value:.2f}")
        delta = ""
        if "baseline" in conditions and "augmented" in conditions:
            base = means.loc["baseline", metric]
            aug = means.loc["augmented", metric]
            if not pd.isna(base) and not pd.isna(aug) and base != 0:
                delta = f"{(aug - base) / base * 100:+.1f}%"
        lines.append(f"| {metric} | " + " | ".join(cells) + f" | {delta} |")
    return "\n".join(lines) + "\n"


def write_report(root: Path) -> None:
    root = Path(root)
    df = load_runs(root)
    df.to_csv(root / "summary.csv", index=False)
    (root / "summary.md").write_text(_to_markdown(df))
