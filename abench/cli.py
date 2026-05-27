# abench/cli.py
from __future__ import annotations

import argparse
from pathlib import Path

from .report import write_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="abench")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="run an experiment")
    run_p.add_argument("experiment", help="path to experiment YAML")

    report_p = sub.add_parser("report", help="build summary from a run dir")
    report_p.add_argument("run_dir", help="path to runs/<name> directory")

    args = parser.parse_args(argv)

    if args.cmd == "report":
        write_report(Path(args.run_dir))
        return 0

    if args.cmd == "run":
        # Wired in Phase 2 once RealOpenCodeClient exists.
        from .config import load_experiment
        from .opencode_client import RealOpenCodeClient
        from .runner import run_experiment

        exp = load_experiment(args.experiment)
        root = run_experiment(exp, lambda e: RealOpenCodeClient(e.opencode, e.timeout_s))
        write_report(root)
        return 0

    return 1
