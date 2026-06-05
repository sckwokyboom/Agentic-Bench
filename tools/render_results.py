#!/usr/bin/env python3
"""Render an abench results CSV into a slide-ready table (standalone, stdlib-only).

Input  : the per-run CSV exported from the Results page ("Download runs .csv"),
         with columns condition,rep,verify,success,duration_s,steps,tool_calls,
         test_runs,cost,service_errors.
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

    INK, MUTED, LINE, GOOD, BAD = "#0f172a", "#64748b", "#e2e8f0", "#16a34a", "#dc2626"
    ZEBRA, CARD_R = "#f1f5f9", 18
    W = 1000
    MARGIN = 26          # transparent gutter so the PNG has rounded corners
    PAD_IN = 36          # padding inside the card
    OX = MARGIN + PAD_IN  # content left edge
    TITLE_FS, SUB_FS, HEAD_FS, CELL_FS = 30, 15, 13, 18
    HEADER_H, ROW_H = 40, 48

    numeric_cols = conds + (["Δ aug vs base"] if has_delta else [])
    metric_w = 230
    table_w = W - 2 * OX
    col_w = (table_w - metric_w) / len(numeric_cols)

    def col_right(j: int) -> int:  # right edge (minus padding) of numeric column j
        return int(OX + metric_w + col_w * (j + 1) - 14)

    title_y = MARGIN + PAD_IN + TITLE_FS
    sub_y = title_y + 26
    table_top = sub_y + 28
    table_bottom = table_top + HEADER_H + len(METRICS) * ROW_H
    foot_y = table_bottom + 26
    height = int(foot_y + 14 + MARGIN)

    def esc(s) -> str:
        return html.escape(str(s))

    # White rounded "card"; nothing is drawn outside it, so the rasterised PNG
    # has transparent (rounded) corners that sit cleanly on any slide.
    el: list[str] = [
        f'<rect x="{MARGIN}" y="{MARGIN}" width="{W - 2 * MARGIN}" '
        f'height="{height - 2 * MARGIN}" rx="{CARD_R}" ry="{CARD_R}" '
        f'fill="#ffffff" stroke="{LINE}"/>'
    ]
    el.append(f'<text x="{OX}" y="{title_y}" font-size="{TITLE_FS}" font-weight="700" '
              f'fill="{INK}">{esc(title)}</text>')
    sub = f"model: {model}     ·     agent: {agent}     ·     runs: {len(rows)}"
    el.append(f'<text x="{OX}" y="{sub_y}" font-size="{SUB_FS}" fill="{MUTED}">{esc(sub)}</text>')

    hb = int(table_top + HEADER_H * 0.66)
    el.append(f'<text x="{OX}" y="{hb}" font-size="{HEAD_FS}" fill="{MUTED}">metric</text>')
    for j, c in enumerate(numeric_cols):
        label = c if c == "Δ aug vs base" else f'{c} (n={agg[c]["n"]})'
        el.append(f'<text x="{col_right(j)}" y="{hb}" font-size="{HEAD_FS}" fill="{MUTED}" '
                  f'text-anchor="end">{esc(label)}</text>')
    line_y = table_top + HEADER_H
    el.append(f'<line x1="{OX}" y1="{line_y}" x2="{W - OX}" y2="{line_y}" stroke="{LINE}"/>')

    for r, (col, label, kind, direction) in enumerate(METRICS):
        row_top = table_top + HEADER_H + r * ROW_H
        if r % 2 == 0:  # zebra: 1st, 3rd, 5th rows (matches the HTML view)
            el.append(f'<rect x="{OX}" y="{row_top}" width="{table_w}" height="{ROW_H}" '
                      f'rx="6" ry="6" fill="{ZEBRA}"/>')
        base = int(row_top + ROW_H * 0.62)
        el.append(f'<text x="{OX}" y="{base}" font-size="{CELL_FS}" fill="{MUTED}">{esc(label)}</text>')
        for j, c in enumerate(conds):
            el.append(f'<text x="{col_right(j)}" y="{base}" font-size="{CELL_FS}" fill="{INK}" '
                      f'text-anchor="end">{esc(_fmt(kind, agg[c].get(col)))}</text>')
        if has_delta:
            txt, cls = _delta(kind, direction, agg["baseline"].get(col), agg["augmented"].get(col))
            color = {"good": GOOD, "bad": BAD}.get(cls, MUTED)
            el.append(f'<text x="{col_right(len(conds))}" y="{base}" font-size="{CELL_FS}" '
                      f'font-weight="700" fill="{color}" text-anchor="end">{esc(txt)}</text>')

    el.append(f'<text x="{OX}" y="{foot_y}" font-size="12" fill="{MUTED}">'
              f'mean per condition · Δ = augmented vs baseline · generated by abench</text>')

    svg = (
        f'<svg id="slide" xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" '
        f'viewBox="0 0 {W} {height}" '
        f"font-family=\"-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif\">\n"
        + "\n".join("  " + e for e in el)
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
