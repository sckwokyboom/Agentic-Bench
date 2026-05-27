# abench/report.py
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

NUMERIC = [
    "duration_s", "n_steps", "n_tool_calls", "n_test_runs", "n_reads",
    "n_searches", "n_files_edited", "diff_lines_added", "diff_lines_removed",
    "tokens_in", "tokens_out", "cost", "time_to_first_edit_s",
]


def load_runs(root: Path) -> pd.DataFrame:
    rows = []
    for metrics_file in sorted(Path(root).glob("*/*/metrics.json")):
        metrics = json.loads(metrics_file.read_text())
        manifest = json.loads((metrics_file.parent / "manifest.json").read_text())
        row = {"condition": manifest["condition"], "rep": manifest["rep"]}
        row.update({k: metrics.get(k) for k in NUMERIC})
        row["finished"] = metrics.get("finished")
        row["interrupted_reason"] = metrics.get("interrupted_reason")
        row["success"] = metrics.get("success")
        rows.append(row)
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    valid = df[df["interrupted_reason"].isna()]
    return valid.groupby("condition")[NUMERIC].agg(["mean", "median", "std"])


def _to_markdown(df: pd.DataFrame) -> str:
    valid = df[df["interrupted_reason"].isna()]
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
