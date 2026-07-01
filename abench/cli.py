# abench/cli.py
from __future__ import annotations

import argparse
import sys
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

    analyze_p = sub.add_parser(
        "analyze", help="screening comparison (ratio+CI, Cliff's, Beta, cost/pass) from a run dir")
    analyze_p.add_argument("run_dir", help="path to the batch dir holding <condition>/<rep>/metrics.json")
    analyze_p.add_argument("--baseline", default="baseline", help="reference condition (default: baseline)")
    analyze_p.add_argument("--agg", default="median", choices=["median", "mean"])
    analyze_p.add_argument("--json", action="store_true", help="emit the panel as JSON instead of text")

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

    lib_p = sub.add_parser("lib", help="manage the local library path registry")
    lib_sub = lib_p.add_subparsers(dest="lib_cmd", required=True)
    lib_add = lib_sub.add_parser("add", help="register/update a library path")
    lib_add.add_argument("name")
    lib_add.add_argument("path")
    lib_sub.add_parser("list", help="list registered library paths")

    vt_p = sub.add_parser(
        "validate-tool",
        help="check that an OpenCode custom tool loads in the experiment's sandbox")
    vt_p.add_argument("experiment", help="path to experiment YAML")
    vt_p.add_argument("tool", help="path to the tool .ts file")

    vm_p = sub.add_parser(
        "validate-model",
        help="check the experiment's model is reachable from its sandbox")
    vm_p.add_argument("experiment", help="path to experiment YAML")

    args = parser.parse_args(argv)

    if args.cmd == "report":
        write_report(Path(args.run_dir))
        return 0

    if args.cmd == "analyze":
        import json as _json

        from .screening import panel_from_dir, render_text
        panel = panel_from_dir(Path(args.run_dir), baseline=args.baseline, agg=args.agg)
        print(_json.dumps(panel, indent=2) if args.json else render_text(panel))
        return 0

    if args.cmd == "run":
        # Wired in Phase 2 once RealOpenCodeClient exists.
        from .opencode_client import RealOpenCodeClient
        from .runner import run_experiment

        exp = load_experiment(args.experiment)

        # Surface the quiet startup phases (baseline verify, image build,
        # workdir prep) that otherwise only reach the UI — one line each, no
        # per-step agent noise (that already streams via the runner's logger).
        _seen_phases: set = set()

        def _cli_progress(p: dict) -> None:
            phase = p.get("phase")
            if phase not in (
                "baseline_verify", "building_sandbox_image", "preparing_workdir"
            ):
                return
            key = (phase, p.get("run_idx"))
            if key in _seen_phases:
                return
            _seen_phases.add(key)
            sys.stderr.write(f"[abench] {p.get('message', phase)}\n")
            sys.stderr.flush()

        root = run_experiment(
            exp,
            lambda e: RealOpenCodeClient(e.opencode, e.timeout_s),
            batch_id=args.batch_id,
            progress=_cli_progress,
        )
        print(f"batch: {root.name}")
        if exp.benchmark is None:
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

    if args.cmd == "lib":
        from . import libraries
        if args.lib_cmd == "add":
            f = libraries.save_library(args.name, args.path)
            print(f"registered {args.name} -> {args.path} in {f}")
            return 0
        if args.lib_cmd == "list":
            reg = libraries.load_registry()
            if not reg:
                print("(no libraries registered)")
            for name, path in sorted(reg.items()):
                print(f"{name}\t{path}")
            return 0
        return 1

    if args.cmd == "validate-tool":
        from . import tool_validation
        exp = load_experiment(args.experiment)  # module-level import
        r = tool_validation.validate_tool(
            Path(args.tool), sandbox=exp.opencode.sandbox,
            agent=exp.opencode.agent, model=exp.model)
        if r.registered:
            print(f"✓ {r.tool_name} registered")
            return 0
        print(f"✗ {r.tool_name} NOT registered (exit {r.exit_code})")
        for e in r.errors:
            print(f"  - {e}")
        return 1

    if args.cmd == "validate-model":
        from . import reachability
        exp = load_experiment(args.experiment)
        prov = exp.opencode.providers[0] if exp.opencode.providers else None
        model = exp.model.split("/", 1)[1] if "/" in exp.model else exp.model
        if prov is None:
            print("no provider configured in experiment.opencode.providers")
            return 1
        r = reachability.validate_reachability(prov, model, sandbox=exp.opencode.sandbox)
        if r.reachable:
            print(f"✓ {model} reachable")
            return 0
        print(f"✗ {model} unreachable — {r.reason}: {r.detail}")
        return 1

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
        ref_text = None
        if exp.target_file:
            rt = exp.reference_path / exp.target_file
            if rt.is_file():
                ref_text = rt.read_text(encoding="utf-8")
        n = recompute_batch(rd, mcfg, reference_target_text=ref_text,
                            target_file=exp.target_file,
                            target_methods=exp.target_methods)
        print(f"recomputed {n} run(s) in {rd}")
        return 0

    return 1
