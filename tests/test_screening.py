import pandas as pd

from abench.screening import (
    aggregate, bootstrap_ratio_ci, cliffs_delta, wilson_ci, beta_prob_gt, build_panel,
)


def test_cliffs_delta_extremes():
    assert cliffs_delta([2, 3, 4], [1, 1, 1]) == 1.0
    assert cliffs_delta([1, 1, 1], [2, 3, 4]) == -1.0
    assert cliffs_delta([1, 2, 3], [1, 2, 3]) == 0.0


def test_wilson_ci_bounds():
    lo, hi = wilson_ci(5, 5)
    assert hi <= 1.0 and lo < 1.0 and lo > 0.0
    assert wilson_ci(0, 0) is None


def test_beta_prob_gt_monotonic():
    strong = beta_prob_gt(5, 5, 0, 5)   # 5/5 vs 0/5
    weak = beta_prob_gt(3, 5, 2, 5)     # 3/5 vs 2/5
    assert strong > 0.95
    assert 0.5 < weak < strong


def test_bootstrap_ratio_ci_is_deterministic_and_brackets_point():
    cond = [1200, 1300, 1400]
    base = [1000, 1100, 1200]
    r1 = bootstrap_ratio_ci(cond, base, agg="median", seed=0)
    r2 = bootstrap_ratio_ci(cond, base, agg="median", seed=0)
    assert r1 == r2                       # seeded → reproducible
    ratio, lo, hi = r1
    assert abs(ratio - (1300 / 1100)) < 1e-9
    assert lo <= ratio <= hi
    assert bootstrap_ratio_ci([], base) is None


def test_aggregate_median_vs_mean_diverge_on_outlier():
    xs = [1000, 1100, 1200, 1300, 5000]   # heavy tail
    assert aggregate(xs, "median") == 1200
    assert aggregate(xs, "mean") > 1200


def _df():
    rows = []
    def add(cond, rep, dur, tin, tout, treas, steps, success):
        rows.append({
            "condition": cond, "rep": rep, "duration_s": dur,
            "tokens_in": tin, "tokens_out": tout, "tokens_reasoning": treas,
            "n_steps": steps, "n_tool_calls": steps,  # stand-in
            "interrupted_reason": None, "n_service_errors": 0,
            "success": success, "verify_status": "passed",
        })
    add("baseline", 0, 1000, 40, 60, 0, 100, True)
    add("baseline", 1, 1100, 42, 62, 0, 110, True)
    add("baseline", 2, 1200, 44, 64, 0, 120, False)
    add("augmented", 0, 1200, 50, 70, 0, 130, True)
    add("augmented", 1, 1300, 52, 72, 0, 140, True)
    add("augmented", 2, 1400, 54, 74, 0, 150, True)
    return pd.DataFrame(rows)


def test_build_panel_shape_and_values():
    panel = build_panel(_df(), baseline="baseline", agg="median")
    assert panel["valid_runs"] == 6
    conds = {c["name"]: c for c in panel["conditions"]}
    base, aug = conds["baseline"], conds["augmented"]

    # baseline is the reference: no ratio
    assert base["metrics"]["duration_s"]["ratio"] is None
    assert base["verdict"] == "baseline"

    # augmented duration ratio = median(1300)/median(1100)
    dr = aug["metrics"]["duration_s"]
    assert abs(dr["ratio"] - (1300 / 1100)) < 1e-9
    assert dr["ci"][0] <= dr["ratio"] <= dr["ci"][1]

    # pass rates + Bayesian comparison
    assert (base["pass"]["k"], base["pass"]["n"]) == (2, 3)
    assert (aug["pass"]["k"], aug["pass"]["n"]) == (3, 3)
    assert aug["pass"]["beta_p_gt_baseline"] > 0.5

    # cost / pass present, augmented better-or-worse computed
    assert aug["cost_per_pass"]["tokens"] is not None
    # better pass rate + only modest cost ratios → promising
    assert aug["verdict"] in ("promising", "inconclusive")


def test_build_panel_empty():
    panel = build_panel(pd.DataFrame(), baseline="baseline")
    assert panel["conditions"] == [] and panel["valid_runs"] == 0


def _df_rich():
    """Two conditions with verify counts, file edits and a tool-call breakdown so
    the outcome (tests-passed %) and behaviour (tool shares) blocks have inputs."""
    rows = []

    def add(cond, rep, success, passed, failed, expected, files, by_name):
        rows.append({
            "condition": cond, "rep": rep, "duration_s": 1000.0,
            "n_steps": 100, "n_tool_calls": sum(by_name.values()),
            "n_reads": by_name.get("read", 0), "n_searches": by_name.get("grep", 0),
            "n_files_edited": files, "tool_calls_by_name": by_name,
            "interrupted_reason": None, "n_service_errors": 0,
            "success": success, "verify_status": "passed" if success else "failed",
            "verify_passed_count": passed, "verify_failed_count": failed,
            "verify_expected_total": expected,
        })

    add("baseline", 0, True, 100, 0, 100, 4, {"read": 6, "grep": 3, "edit": 1, "bash": 10})
    add("baseline", 1, True, 100, 0, 100, 4, {"read": 6, "grep": 3, "edit": 1, "bash": 10})
    add("forced", 0, False, 95, 5, 100, 38, {"read": 3, "grep": 1, "edit": 20, "bash": 16})
    add("forced", 1, True, 100, 0, 100, 30, {"read": 3, "grep": 1, "edit": 18, "bash": 18})
    return pd.DataFrame(rows)


def test_build_panel_tests_pass_rate_and_behavior():
    panel = build_panel(_df_rich(), baseline="baseline", agg="median")
    conds = {c["name"]: c for c in panel["conditions"]}
    base, forced = conds["baseline"], conds["forced"]

    # outcome: Σpassed / Σ(passed+failed), full expected suite in the denominator
    assert base["tests_pass_rate"] == 1.0
    assert abs(forced["tests_pass_rate"] - (195 / 200)) < 1e-9

    # behaviour: read/search/edit/bash as a share of all tool calls, summed
    b = base["behavior"]
    assert b["tool_calls"] == 40.0           # (6+3+1+10) * 2 runs
    assert abs(b["read_share"] - 12 / 40) < 1e-9
    assert abs(b["bash_share"] - 20 / 40) < 1e-9
    assert abs(b["edit_share"] - 2 / 40) < 1e-9
    assert base["behavior"]["files_edited"] == 4   # median of [4, 4]
    # forced edits much higher (instrument-the-test arm rewrites the suite)
    assert forced["behavior"]["edit_share"] > base["behavior"]["edit_share"]


def test_behavior_absent_inputs_yield_none():
    # The lean _df() has no tool_calls_by_name / n_reads → shares are None, no crash.
    panel = build_panel(_df(), baseline="baseline")
    beh = panel["conditions"][0]["behavior"]
    assert beh["read_share"] is None and beh["edit_share"] is None
