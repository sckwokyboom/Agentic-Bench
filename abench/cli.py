# abench/cli.py
from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_experiment
from .report import write_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="abench")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="run an experiment")
    run_p.add_argument("experiment", help="path to experiment YAML")
    run_p.add_argument(
        "--batch-id", default=None,
        help="batch dir name under output_dir/<exp>/ (default: UTC timestamp)")

    report_p = sub.add_parser("report", help="build summary from a run dir")
    report_p.add_argument("run_dir", help="path to runs/<name> directory")

    verify_p = sub.add_parser(
        "verify", help="re-verify saved run(s) without re-running the agent")
    verify_p.add_argument("experiment", help="path to experiment YAML")
    verify_p.add_argument("--condition", default=None)
    verify_p.add_argument("--rep", type=int, default=None)
    verify_p.add_argument(
        "--batch", default=None,
        help="batch dir name under output_dir/<exp>/ (default: newest batch, "
             "or the flat/legacy layout if that's all that exists)")

    recompute_p = sub.add_parser(
        "recompute",
        help="recompute metrics for saved run(s) from trace.json (no agent re-run)")
    recompute_p.add_argument("experiment", help="path to experiment YAML")
    recompute_p.add_argument(
        "--batch", default=None,
        help="batch dir name (default: newest batch / legacy layout)")

    args = parser.parse_args(argv)

    if args.cmd == "report":
        write_report(Path(args.run_dir))
        return 0

    if args.cmd == "run":
        # Wired in Phase 2 once RealOpenCodeClient exists.
        from .opencode_client import RealOpenCodeClient
        from .runner import run_experiment

        exp = load_experiment(args.experiment)
        root = run_experiment(
            exp,
            lambda e: RealOpenCodeClient(e.opencode, e.timeout_s),
            batch_id=args.batch_id,
        )
        print(f"batch: {root.name}")
        write_report(root)
        return 0

    if args.cmd == "verify":
        from . import reverify

        exp = load_experiment(args.experiment)
        if args.condition is not None and args.rep is not None:
            results = [(args.condition, args.rep,
                        reverify.reverify_run(exp, args.condition, args.rep,
                                              batch=args.batch))]
        else:
            results = list(reverify.reverify_experiment(exp, batch=args.batch))
        for cond, rep, v in results:
            if v.passed_count is not None:
                total = (v.passed_count or 0) + (v.failed_count or 0)
                counts = f" ({v.passed_count}/{total})"
            else:
                counts = ""
            print(f"{cond}/rep_{rep} → {v.status}/{v.reason}{counts}")
        return 0

    if args.cmd == "recompute":
        from .metrics import MetricsConfig
        from .recompute import recompute_batch
        from .run_layout import batch_runs_dir

        exp = load_experiment(args.experiment)
        rd = batch_runs_dir(exp.output_dir / exp.name, args.batch)
        if rd is None:
            print("no runs to recompute")
            return 1
        mcfg = MetricsConfig(**exp.metrics.model_dump())
        n = recompute_batch(rd, mcfg)
        print(f"recomputed {n} run(s) in {rd}")
        return 0

    return 1
