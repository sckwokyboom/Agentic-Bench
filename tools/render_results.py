#!/usr/bin/env python3
"""Render an abench results CSV into a slide-ready table (standalone, stdlib-only).

Input  : the per-run CSV exported from the Results page ("Download runs .csv"),
         with columns condition,rep,verify,success,duration_s,steps,tool_calls,
         test_runs,cost,service_errors.
Output : a self-contained, print-clean HTML file aggregating the runs (mean per
         condition + Δ augmented-vs-baseline), with a labelled header. Open it in
         a browser and screenshot, or Cmd/Ctrl+P → "Save as PDF" for the slide.

No dependencies — runs with any python3.

Example:
    python3 tools/render_results.py picocli-putValue.csv \\
        --model "DeepSeek v4 flash" --agent opencode \\
        --title "picocli · putValue" -o slide.html
"""
from __future__ import annotations

import argparse
import csv
import html
from pathlib import Path

# (csv column, label, value format, direction) — direction drives Δ colouring:
# "lower" → a negative Δ is good (green); "higher" → positive Δ is good.
METRICS = [
    ("success_rate", "success rate", "pct", "higher"),
    ("steps", "steps", "num", "lower"),
    ("tool_calls", "tool calls", "num", "lower"),
    ("test_runs", "test runs", "num", "lower"),
    ("duration_s", "duration (min)", "min", "lower"),
]


def _to_float(s: str):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def aggregate(rows: list[dict]) -> dict[str, dict]:
    """Per-condition aggregates: mean of numeric columns + success rate + n."""
    by_cond: dict[str, list[dict]] = {}
    for r in rows:
        by_cond.setdefault(r.get("condition", "?"), []).append(r)

    out: dict[str, dict] = {}
    for cond, items in by_cond.items():
        agg: dict[str, float | None] = {"n": len(items)}
        for col in ("steps", "tool_calls", "test_runs", "duration_s", "cost"):
            vals = [v for v in (_to_float(r.get(col, "")) for r in items) if v is not None]
            agg[col] = sum(vals) / len(vals) if vals else None
        verdicts = [r.get("success", "") for r in items if r.get("success") in ("pass", "fail")]
        agg["success_rate"] = (
            100.0 * sum(v == "pass" for v in verdicts) / len(verdicts) if verdicts else None
        )
        out[cond] = agg
    return out


def _order_conditions(conds: list[str]) -> list[str]:
    pref = {"baseline": 0, "augmented": 1}
    return sorted(conds, key=lambda c: (pref.get(c, 2), c))


def _fmt(kind: str, v: float | None) -> str:
    if v is None:
        return "—"
    if kind == "pct":
        return f"{v:.0f}%"
    if kind == "min":  # value is in seconds → minutes
        return f"{v / 60:.1f}"
    return f"{v:.1f}"


def _delta(kind: str, direction: str, base, aug):
    """Return (text, css-class) for the Δ cell, or ('—','neutral')."""
    if base is None or aug is None:
        return "—", "neutral"
    if kind == "pct":  # percentage-points
        d = aug - base
        cls = "neutral" if d == 0 else ("good" if (d > 0) == (direction == "higher") else "bad")
        return f"{'+' if d > 0 else ''}{d:.0f}pp", cls
    if base == 0:
        return "—", "neutral"
    d = (aug - base) / base * 100.0
    cls = "neutral" if d == 0 else ("good" if (d < 0) == (direction == "lower") else "bad")
    return f"{'+' if d > 0 else ''}{d:.1f}%", cls


def render_html(rows: list[dict], *, title: str, model: str, agent: str) -> str:
    agg = aggregate(rows)
    conds = _order_conditions(list(agg))
    has_delta = "baseline" in agg and "augmented" in agg

    chips = "".join(
        f'<span class="chip">{html.escape(t)}</span>'
        for t in (f"model: {model}", f"agent: {agent}", f"runs: {len(rows)}")
        if t
    )

    head = "<th>metric</th>" + "".join(
        f'<th class="num">{html.escape(c)} <span class="muted">(n={agg[c]["n"]})</span></th>'
        for c in conds
    ) + ("<th class='num'>Δ aug vs base</th>" if has_delta else "")

    body_rows = []
    for col, label, kind, direction in METRICS:
        cells = "".join(f'<td class="num">{_fmt(kind, agg[c].get(col))}</td>' for c in conds)
        delta_cell = ""
        if has_delta:
            txt, cls = _delta(kind, direction,
                              agg["baseline"].get(col), agg["augmented"].get(col))
            delta_cell = f'<td class="num delta {cls}">{txt}</td>'
        body_rows.append(f"<tr><td>{html.escape(label)}</td>{cells}{delta_cell}</tr>")

    return _TEMPLATE.format(
        title=html.escape(title),
        chips=chips,
        head=head,
        body="\n".join(body_rows),
    )


_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{title}</title>
<style>
  :root {{ --ink:#0f172a; --muted:#64748b; --line:#e2e8f0; --good:#16a34a; --bad:#dc2626; }}
  html,body {{ margin:0; background:#f1f5f9; color:var(--ink);
    font:16px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }}
  .card {{ width:980px; margin:32px auto; background:#fff; border:1px solid var(--line);
    border-radius:16px; padding:36px 40px; box-shadow:0 10px 30px rgba(2,6,23,.08); }}
  h1 {{ font-size:30px; margin:0 0 12px; letter-spacing:-.01em; }}
  .chips {{ margin-bottom:22px; }}
  .chip {{ display:inline-block; margin:0 8px 8px 0; padding:5px 12px; border-radius:999px;
    background:#eef2ff; color:#3730a3; font-size:14px; font-weight:600; }}
  table {{ width:100%; border-collapse:collapse; font-variant-numeric:tabular-nums; }}
  th,td {{ padding:11px 14px; border-bottom:1px solid var(--line); }}
  th {{ text-align:left; font-size:13px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); }}
  td {{ font-size:18px; }}
  td:first-child {{ color:var(--muted); }}
  .num {{ text-align:right; }}
  .muted {{ color:var(--muted); font-weight:400; text-transform:none; letter-spacing:0; }}
  tbody tr:nth-child(odd) {{ background:#f8fafc; }}
  .delta {{ font-weight:700; }}
  .good {{ color:var(--good); }} .bad {{ color:var(--bad); }} .neutral {{ color:var(--muted); }}
  .foot {{ margin-top:18px; color:var(--muted); font-size:12px; }}
  @media print {{ html,body {{ background:#fff; }} .card {{ box-shadow:none; margin:0; border:none; }} }}
</style></head>
<body><div class="card">
  <h1>{title}</h1>
  <div class="chips">{chips}</div>
  <table><thead><tr>{head}</tr></thead>
  <tbody>
{body}
  </tbody></table>
  <div class="foot">mean per condition · Δ = augmented vs baseline · generated by abench</div>
</div></body></html>
"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Render an abench results CSV to a slide-ready HTML table.")
    p.add_argument("csv", help="results CSV exported from the Results page")
    p.add_argument("-o", "--out", default=None, help="output HTML path (default: <csv>.html)")
    p.add_argument("--model", default="DeepSeek v4 flash", help="model label for the header")
    p.add_argument("--agent", default="opencode", help="agent label for the header")
    p.add_argument("--title", default=None, help="slide title (default: the CSV file stem)")
    args = p.parse_args(argv)

    src = Path(args.csv)
    with src.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        p.error(f"no rows in {src}")

    out = Path(args.out) if args.out else src.with_suffix(".html")
    out.write_text(
        render_html(rows, title=args.title or src.stem, model=args.model, agent=args.agent),
        encoding="utf-8",
    )
    print(f"wrote {out.resolve()}")
    print("open it in a browser and screenshot, or Cmd/Ctrl+P → Save as PDF for the slide")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
