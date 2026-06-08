#!/usr/bin/env python3
"""Render an abench results CSV into a slide-ready table (standalone, stdlib-only).

Input  : the per-run CSV exported from the Results page ("Download runs .csv").
         Aggregates whatever of these columns are present: success, tests_pass_rate,
         steps, tool_calls, reads, searches, test_runs, tests_executed, duration_s,
         tokens_in, tokens_out, cost. Missing columns simply render as "—".
Output : a self-contained HTML file rendering the aggregate (mean per condition +
         Δ augmented-vs-baseline) as a crisp SVG table with a labelled header.
         Open it in a browser and click "Download PNG" (the SVG is rasterised to
         a 2× PNG client-side), or Cmd/Ctrl+P → "Save as PDF" for the slide.

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
import json
import math
from pathlib import Path

# (csv column, label, value format, direction) — direction drives Δ colouring:
# "lower" → a negative Δ is good (green); "higher" → positive Δ is good.
METRICS = [
    ("success_rate", "success rate", "pct", "higher"),
    ("tests_pass_rate", "tests passed %", "pct1", "higher"),
    ("tests_executed", "tests executed", "num", "neutral"),
    ("test_runs", "test runs", "num", "lower"),
    ("steps", "steps", "num", "lower"),
    ("tool_calls", "tool calls", "num", "lower"),
    ("duration_s", "duration (min)", "min", "lower"),
    ("tokens_in", "tokens in", "num", "lower"),
    ("tokens_out", "tokens out", "num", "lower"),
]

# Numeric CSV columns the aggregate averages per condition.
_NUM_COLS = ("steps", "tool_calls", "reads", "searches", "test_runs",
             "tests_executed", "duration_s", "tokens_in", "tokens_out", "cost")


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
        for col in _NUM_COLS:
            vals = [v for v in (_to_float(r.get(col, "")) for r in items) if v is not None]
            agg[col] = sum(vals) / len(vals) if vals else None
        verdicts = [r.get("success", "") for r in items if r.get("success") in ("pass", "fail")]
        agg["success_rate"] = (
            100.0 * sum(v == "pass" for v in verdicts) / len(verdicts) if verdicts else None
        )
        # tests passed %: prefer SUMMED verify counts (Σpassed/Σtotal) — robust to
        # runs missing the derived tests_pass_rate column and keeps failing runs in
        # the denominator. Fall back to the mean of the 0..1 per-run fractions.
        tot_p = tot_t = 0.0
        for r in items:
            p = _to_float(r.get("verify_passed", "") or r.get("verify_passed_count", ""))
            f = _to_float(r.get("verify_failed", "") or r.get("verify_failed_count", ""))
            if p is not None and f is not None and (p + f) > 0:
                tot_p += p
                tot_t += p + f
        if tot_t:
            agg["tests_pass_rate"] = 100.0 * tot_p / tot_t
        else:
            prates = [v for v in (_to_float(r.get("tests_pass_rate", "")) for r in items)
                      if v is not None]
            agg["tests_pass_rate"] = 100.0 * sum(prates) / len(prates) if prates else None
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
    if kind == "pct1":  # one decimal, FLOORED so 99.96% never rounds up to 100.0%
        return f"{math.floor(v * 10) / 10:.1f}%"
    if kind == "min":  # value is in seconds → minutes
        return f"{v / 60:.1f}"
    return f"{v:.1f}"


def _delta(kind: str, direction: str, base, aug):
    """Return (text, css-class) for the Δ cell, or ('—','neutral')."""
    if base is None or aug is None:
        return "—", "neutral"
    if kind in ("pct", "pct1"):  # percentage-points
        d = aug - base
        dec = 1 if kind == "pct1" else 0
        if direction == "neutral":
            return f"{d:+.{dec}f}pp", "neutral"
        cls = "neutral" if d == 0 else ("good" if (d > 0) == (direction == "higher") else "bad")
        return f"{d:+.{dec}f}pp", cls
    if base == 0:
        return "—", "neutral"
    d = (aug - base) / base * 100.0
    if direction == "neutral":
        return f"{d:+.1f}%", "neutral"
    cls = "neutral" if d == 0 else ("good" if (d < 0) == (direction == "lower") else "bad")
    return f"{d:+.1f}%", cls


def tool_distribution(rows: list[dict], conds: list[str]):
    """Per-condition MEAN tool calls/run from the runs CSV's tool_calls_by_name
    JSON column. Returns ({cond: {tool: mean_per_run}}, ordered_tool_names). The
    column is absent in older CSVs → returns ({}, [])."""
    per: dict[str, dict[str, float]] = {c: {} for c in conds}
    counts = {c: 0 for c in conds}
    totals: dict[str, float] = {}
    for r in rows:
        c = r.get("condition", "?")
        if c not in per:
            continue
        counts[c] += 1
        raw = r.get("tool_calls_by_name") or ""
        try:
            dist = json.loads(raw) if raw else {}
        except (ValueError, TypeError):
            dist = {}
        for tool, n in (dist or {}).items():
            if isinstance(n, (int, float)):
                per[c][tool] = per[c].get(tool, 0.0) + n
                totals[tool] = totals.get(tool, 0.0) + n
    if not totals:
        return {}, []
    for c in per:
        denom = counts[c] or 1
        per[c] = {t: v / denom for t, v in per[c].items()}
    tools = sorted(totals, key=lambda t: -totals[t])[:12]
    return per, tools


def render_html(rows: list[dict], *, title: str, model: str, agent: str) -> str:
    agg = aggregate(rows)
    conds = _order_conditions(list(agg))
    has_delta = "baseline" in agg and "augmented" in agg
    tool_per, tool_names = tool_distribution(rows, conds)

    INK, MUTED, LINE, GOOD, BAD = "#0f172a", "#64748b", "#e2e8f0", "#16a34a", "#dc2626"
    ZEBRA, CARD_R = "#f1f5f9", 18
    W = 1000
    MARGIN = 26          # transparent gutter so the PNG has rounded corners
    PAD_IN = 36          # padding inside the card
    OX = MARGIN + PAD_IN  # content left edge
    TITLE_FS, SUB_FS, HEAD_FS, CELL_FS, SEC_FS = 30, 15, 13, 18, 15
    HEADER_H, ROW_H = 40, 48

    numeric_cols = conds + (["Δ aug vs base"] if has_delta else [])
    metric_w = 230
    table_w = W - 2 * OX
    col_w = (table_w - metric_w) / len(numeric_cols)

    def col_right(j: int) -> int:  # right edge (minus padding) of numeric column j
        return int(OX + metric_w + col_w * (j + 1) - 14)

    def esc(s) -> str:
        return html.escape(str(s))

    el: list[str] = []  # SVG body; card rect is prepended once height is known

    def draw_block(top: int, first_col: str, specs: list[tuple]) -> int:
        """specs: list of (label, {cond: text}, (delta_text, delta_cls)|None).
        Draws a header row + data rows (zebra); returns the y below the block."""
        hb = int(top + HEADER_H * 0.66)
        el.append(f'<text x="{OX}" y="{hb}" font-size="{HEAD_FS}" fill="{MUTED}">{esc(first_col)}</text>')
        for j, c in enumerate(numeric_cols):
            lbl = c if c == "Δ aug vs base" else f'{c} (n={agg[c]["n"]})'
            el.append(f'<text x="{col_right(j)}" y="{hb}" font-size="{HEAD_FS}" fill="{MUTED}" '
                      f'text-anchor="end">{esc(lbl)}</text>')
        el.append(f'<line x1="{OX}" y1="{top + HEADER_H}" x2="{W - OX}" y2="{top + HEADER_H}" stroke="{LINE}"/>')
        for r, (label, cells, delta) in enumerate(specs):
            row_top = top + HEADER_H + r * ROW_H
            if r % 2 == 0:
                el.append(f'<rect x="{OX}" y="{row_top}" width="{table_w}" height="{ROW_H}" '
                          f'rx="6" ry="6" fill="{ZEBRA}"/>')
            base = int(row_top + ROW_H * 0.62)
            el.append(f'<text x="{OX}" y="{base}" font-size="{CELL_FS}" fill="{MUTED}">{esc(label)}</text>')
            for j, c in enumerate(conds):
                el.append(f'<text x="{col_right(j)}" y="{base}" font-size="{CELL_FS}" fill="{INK}" '
                          f'text-anchor="end">{esc(cells.get(c, "—"))}</text>')
            if has_delta and delta is not None:
                txt, cls = delta
                color = {"good": GOOD, "bad": BAD}.get(cls, MUTED)
                el.append(f'<text x="{col_right(len(conds))}" y="{base}" font-size="{CELL_FS}" '
                          f'font-weight="700" fill="{color}" text-anchor="end">{esc(txt)}</text>')
        return top + HEADER_H + len(specs) * ROW_H

    # Row specs --------------------------------------------------------------
    metric_specs = []
    for col, label, kind, direction in METRICS:
        cells = {c: _fmt(kind, agg[c].get(col)) for c in conds}
        delta = (_delta(kind, direction, agg["baseline"].get(col), agg["augmented"].get(col))
                 if has_delta else None)
        metric_specs.append((label, cells, delta))

    tool_specs = []
    for tool in tool_names:
        cells = {c: _fmt("num", tool_per[c].get(tool)) for c in conds}
        delta = (_delta("num", "neutral", tool_per["baseline"].get(tool),
                        tool_per["augmented"].get(tool)) if has_delta else None)
        tool_specs.append((tool, cells, delta))

    # Layout -----------------------------------------------------------------
    title_y = MARGIN + PAD_IN + TITLE_FS
    sub_y = title_y + 26
    m_top = sub_y + 28
    title_el = [
        f'<text x="{OX}" y="{title_y}" font-size="{TITLE_FS}" font-weight="700" fill="{INK}">{esc(title)}</text>',
        f'<text x="{OX}" y="{sub_y}" font-size="{SUB_FS}" fill="{MUTED}">'
        f'{esc(f"model: {model}     ·     agent: {agent}     ·     runs: {len(rows)}")}</text>',
    ]
    el.extend(title_el)
    m_bottom = draw_block(m_top, "metric", metric_specs)

    if tool_specs:
        sec_y = m_bottom + 34
        el.append(f'<text x="{OX}" y="{sec_y}" font-size="{SEC_FS}" font-weight="700" '
                  f'fill="{INK}">Tool calls (mean per run)</text>')
        bottom = draw_block(sec_y + 12, "tool", tool_specs)
    else:
        bottom = m_bottom

    foot_y = bottom + 26
    height = int(foot_y + 14 + MARGIN)
    el.append(f'<text x="{OX}" y="{foot_y}" font-size="12" fill="{MUTED}">'
              f'mean per condition · Δ = augmented vs baseline · generated by abench</text>')

    card = (
        f'<rect x="{MARGIN}" y="{MARGIN}" width="{W - 2 * MARGIN}" '
        f'height="{height - 2 * MARGIN}" rx="{CARD_R}" ry="{CARD_R}" '
        f'fill="#ffffff" stroke="{LINE}"/>'
    )
    svg = (
        f'<svg id="slide" xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" '
        f'viewBox="0 0 {W} {height}" '
        f"font-family=\"-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif\">\n"
        + "\n".join("  " + e for e in [card, *el])
        + "\n</svg>"
    )
    return (_TEMPLATE
            .replace("__TITLE__", html.escape(title))
            .replace("__FNAME__", json.dumps(title))
            .replace("__SVG__", svg))


# Plain string + token replace (NOT .format) so the CSS/JS braces need no escaping.
_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>__TITLE__</title>
<style>
  html,body { margin:0; background:#f1f5f9;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }
  .wrap { display:flex; flex-direction:column; align-items:center; gap:16px; padding:28px; }
  .toolbar { display:flex; align-items:center; gap:12px; }
  .card { background:#fff; border:1px solid #e2e8f0; border-radius:16px;
    box-shadow:0 10px 30px rgba(2,6,23,.08); overflow:hidden; }
  button { font:600 14px/1 system-ui; padding:10px 16px; border:1px solid #c7d2fe;
    background:#eef2ff; color:#3730a3; border-radius:10px; cursor:pointer; }
  button:hover { background:#e0e7ff; }
  .hint { color:#64748b; font:13px system-ui; }
  @media print { .toolbar { display:none; } body { background:#fff; } .card { box-shadow:none; border:none; } }
</style></head>
<body><div class="wrap">
  <div class="toolbar">
    <button onclick="downloadPng()">⬇ Download PNG</button>
    <span class="hint">or Cmd/Ctrl+P → Save as PDF</span>
  </div>
  <div class="card">__SVG__</div>
</div>
<script>
  const FNAME = __FNAME__;
  function downloadPng() {
    const svg = document.getElementById('slide');
    const xml = new XMLSerializer().serializeToString(svg);
    const url = 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(xml)));
    const img = new Image();
    img.onload = function () {
      const scale = 2, vb = svg.viewBox.baseVal;
      const c = document.createElement('canvas');
      c.width = vb.width * scale; c.height = vb.height * scale;
      const ctx = c.getContext('2d'); ctx.scale(scale, scale); ctx.drawImage(img, 0, 0);
      c.toBlob(function (blob) {
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob); a.download = FNAME + '.png';
        document.body.appendChild(a); a.click(); a.remove();
        URL.revokeObjectURL(a.href);
      }, 'image/png');
    };
    img.src = url;
  }
</script></body></html>
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
    print("open it in a browser → click “Download PNG” (or Cmd/Ctrl+P → Save as PDF)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
