# abench/screening.py
"""Screening-grade comparison stats over a batch of runs.

Additive layer on top of report.load_runs: for each condition vs a baseline it
computes the things the small-n A/B decision actually needs — ratio of the
chosen aggregate (median|mean) with a bootstrap CI, Cliff's delta, a Wilson
interval and a Bayesian P(condition > baseline) on the pass rate, cost-per-pass,
and a coarse promising|inconclusive|dominated verdict.

Deliberately NOT p-values: at n≈5 those are underpowered. Effect size + interval
+ raw points (the caller still has the per-run rows) is the honest read. Pure
functions here are seeded, so output is deterministic and testable.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .report import NUMERIC, _valid_runs, load_runs

# Metrics shown in the cost block, in display order (subset of report.NUMERIC
# that is meaningful as a "lower is better" cost ratio).
COST_METRICS = [
    "duration_s", "n_steps", "n_tool_calls", "n_test_runs", "n_tests_executed",
    "n_reads", "n_searches", "n_files_edited",
    "tokens_in", "tokens_out", "tokens_reasoning",
]


def _clean(xs) -> np.ndarray:
    """Drop NaN/None and return a float array."""
    a = pd.to_numeric(pd.Series(list(xs)), errors="coerce").dropna().to_numpy(dtype=float)
    return a


def aggregate(xs, agg: str = "median") -> float | None:
    a = _clean(xs)
    if a.size == 0:
        return None
    return float(np.median(a) if agg == "median" else np.mean(a))


def bootstrap_ratio_ci(cond, base, agg: str = "median",
                       iters: int = 5000, seed: int = 0, conf: float = 0.95):
    """Ratio of aggregate(cond)/aggregate(base) with a percentile bootstrap CI.

    Returns (ratio, lo, hi) or None when either arm is empty or the baseline
    aggregate is ~0. Seeded → deterministic.
    """
    c = _clean(cond)
    b = _clean(base)
    if c.size == 0 or b.size == 0:
        return None
    f = np.median if agg == "median" else np.mean
    base_agg = float(f(b))
    if abs(base_agg) < 1e-12:
        return None
    ratio = float(f(c)) / base_agg
    rng = np.random.default_rng(seed)
    samples = np.empty(iters, dtype=float)
    n = 0
    for i in range(iters):
        bb = float(f(rng.choice(b, size=b.size, replace=True)))
        if abs(bb) < 1e-12:
            continue
        samples[n] = float(f(rng.choice(c, size=c.size, replace=True))) / bb
        n += 1
    if n == 0:
        return (ratio, None, None)
    s = np.sort(samples[:n])
    lo = float(np.quantile(s, (1 - conf) / 2))
    hi = float(np.quantile(s, 1 - (1 - conf) / 2))
    return (ratio, lo, hi)


def cliffs_delta(cond, base) -> float | None:
    """Cliff's delta in [-1, 1]: P(cond>base) - P(cond<base). Robust, nonparametric,
    sensible at tiny n. >0 means cond tends to be larger than base."""
    c = _clean(cond)
    b = _clean(base)
    if c.size == 0 or b.size == 0:
        return None
    diff = c[:, None] - b[None, :]
    gt = int(np.sum(diff > 0))
    lt = int(np.sum(diff < 0))
    return float((gt - lt) / (c.size * b.size))


def wilson_ci(k: int, n: int, z: float = 1.96):
    """Wilson score interval for a binomial proportion; (lo, hi) or None if n==0."""
    if n == 0:
        return None
    p = k / n
    z2 = z * z
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    half = (z * ((p * (1 - p) / n + z2 / (4 * n * n)) ** 0.5)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def beta_prob_gt(k_a: int, n_a: int, k_b: int, n_b: int,
                 samples: int = 20000, seed: int = 0) -> float | None:
    """P(rate_a > rate_b) under uniform Beta(1,1) priors, by sampling. Seeded."""
    if n_a == 0 or n_b == 0:
        return None
    rng = np.random.default_rng(seed)
    a = rng.beta(1 + k_a, 1 + n_a - k_a, samples)
    b = rng.beta(1 + k_b, 1 + n_b - k_b, samples)
    return float(np.mean(a > b))


def _verdict(is_baseline, success_rate, base_rate, cost_ratios) -> str:
    """Coarse screening verdict. cost_ratios = list of (ratio, lo, hi) over cost
    metrics (CI may be None). Direction-aware, intentionally conservative."""
    if is_baseline:
        return "baseline"
    if success_rate is None or base_rate is None:
        return "inconclusive"
    better = success_rate > base_rate + 1e-9
    worse = success_rate < base_rate - 1e-9
    # a cost metric is "robustly costlier" when its whole CI sits above 1
    robustly_costlier = [r for r in cost_ratios
                         if r and r[1] is not None and r[1] > 1.0]
    big = [r for r in robustly_costlier if r[0] >= 2.0]
    if worse and big:
        return "dominated"
    if better and not big:
        return "promising"
    return "inconclusive"


def build_panel(df: pd.DataFrame, baseline: str = "baseline",
                agg: str = "median", seed: int = 0) -> dict:
    """Build the comparison panel dict from a load_runs DataFrame."""
    if df.empty:
        return {"baseline": baseline, "agg": agg, "conditions": [],
                "total_runs": 0, "valid_runs": 0}
    valid = _valid_runs(df)
    total_runs = int(len(df))
    valid_runs = int(len(valid))
    interrupted = int(df["interrupted_reason"].notna().sum())
    present = [m for m in (COST_METRICS + NUMERIC) if m in valid.columns]
    seen, metric_order = set(), []
    for m in present:
        if m not in seen:
            seen.add(m)
            metric_order.append(m)

    def _sub(cond):
        return valid[valid["condition"] == cond]

    base_sub = _sub(baseline)
    base_succ = base_sub["success"].dropna() if "success" in base_sub else pd.Series([], dtype=object)
    base_k = int((base_succ == True).sum())  # noqa: E712
    base_n = int(len(base_succ))
    base_rate = (base_k / base_n) if base_n else None

    conditions = []
    for cond in sorted(df["condition"].unique()):
        full = df[df["condition"] == cond]
        sub = _sub(cond)
        succ = sub["success"].dropna() if "success" in sub else pd.Series([], dtype=object)
        k = int((succ == True).sum())  # noqa: E712
        n = int(len(succ))
        rate = (k / n) if n else None
        is_base = (cond == baseline)

        # cost / pass: total effort over valid runs ÷ passing runs
        cost_tokens = cost_seconds = None
        if k > 0:
            tok_cols = [c for c in ("tokens_in", "tokens_out", "tokens_reasoning") if c in sub]
            if tok_cols:
                tot = float(sub[tok_cols].apply(pd.to_numeric, errors="coerce").fillna(0).to_numpy().sum())
                cost_tokens = tot / k
            if "duration_s" in sub:
                d = pd.to_numeric(sub["duration_s"], errors="coerce").fillna(0).sum()
                cost_seconds = float(d) / k

        flags = {
            "interrupted": int(full["interrupted_reason"].notna().sum()),
            "crashed": int(len(full) - len(sub) - full["interrupted_reason"].notna().sum()),
        }
        if "verify_status" in full:
            flags["invalid_verify"] = int((full["verify_status"] == "invalid").sum())

        metrics = {}
        cost_ratios = []
        for m in metric_order:
            value = aggregate(sub[m], agg) if m in sub else None
            ratio = lo = hi = cliff = None
            if not is_base and m in sub and m in base_sub:
                rc = bootstrap_ratio_ci(sub[m], base_sub[m], agg, seed=seed)
                if rc:
                    ratio, lo, hi = rc
                cliff = cliffs_delta(sub[m], base_sub[m])
            entry = {"value": value, "ratio": ratio,
                     "ci": [lo, hi] if ratio is not None else None, "cliffs": cliff}
            metrics[m] = entry
            if not is_base and m in COST_METRICS and ratio is not None:
                cost_ratios.append((ratio, lo, hi))

        conditions.append({
            "name": str(cond),
            "n_valid": int(len(sub)),
            "n_total": int(len(full)),
            "pass": {
                "k": k, "n": n, "rate": rate,
                "wilson": list(wilson_ci(k, n)) if n else None,
                "beta_p_gt_baseline": (None if is_base else beta_prob_gt(k, n, base_k, base_n, seed=seed)),
            },
            "cost_per_pass": {"tokens": cost_tokens, "seconds": cost_seconds},
            "flags": flags,
            "metrics": metrics,
            "verdict": _verdict(is_base, rate, base_rate, cost_ratios),
        })

    return {
        "baseline": baseline, "agg": agg,
        "total_runs": total_runs, "valid_runs": valid_runs, "interrupted_runs": interrupted,
        "metric_order": metric_order,
        "conditions": conditions,
    }


def panel_from_dir(run_dir: Path, baseline: str = "baseline", agg: str = "median") -> dict:
    return build_panel(load_runs(Path(run_dir)), baseline=baseline, agg=agg)


def render_text(panel: dict) -> str:
    """Compact text rendering for the CLI (sanity check; the Web UI is the real view)."""
    lines = [f"baseline={panel['baseline']}  agg={panel['agg']}  "
             f"runs: {panel['valid_runs']}/{panel['total_runs']} valid"]
    for c in panel["conditions"]:
        p = c["pass"]
        rate = "-" if p["rate"] is None else f"{p['k']}/{p['n']}"
        cpp = c["cost_per_pass"]["tokens"]
        cpp_s = "-" if cpp is None else f"{cpp/1000:.0f}k/pass"
        lines.append(f"\n[{c['name']}]  n_valid={c['n_valid']}  pass={rate}  "
                     f"cost={cpp_s}  verdict={c['verdict']}")
        for m, e in c["metrics"].items():
            if e["value"] is None:
                continue
            r = ""
            if e["ratio"] is not None:
                ci = e["ci"]
                r = f"  {e['ratio']:.2f}x" + (f" [{ci[0]:.2f}-{ci[1]:.2f}]" if ci and ci[0] is not None else "")
            lines.append(f"    {m:18} {e['value']:.4g}{r}")
    return "\n".join(lines)
