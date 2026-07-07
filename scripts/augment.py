"""Thin Agentic-Bench wrapper around Graph-Tipper's kgpool.make: produce a raw pool +
augment.prompt.md for a target, and drop the bundle into an experiment's slices/.

Usage: python scripts/augment.py --project P --target FQN --experiment DIR \
         [--tests name=A,B] [--spec-tests A,B] [--out POOL]
Then run slices/augment.prompt.md through a model, save the result as
slices/forced-instrument-in-test.md, and point experiment.yaml `augmentation:` at it."""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _registry_gt():
    try:
        from abench.libraries import load_registry
        p = load_registry().get("graph-tipper")
        return Path(p) if p else None
    except Exception:
        return None


def resolve_gt() -> Path:
    gt = _registry_gt()
    if gt is None:
        env = os.environ.get("GRAPH_TIPPER_HOME")
        gt = Path(env) if env else None
    if gt is None or not gt.exists():
        sys.exit("Graph-Tipper not found — `abench lib add graph-tipper <path>` "
                 "or set GRAPH_TIPPER_HOME")
    return gt


def run(*, project, target, experiment, out=None, tests=None, spec_tests=None, jacoco=False):
    gt = resolve_gt()
    # Absolutise everything: kgpool.make runs with cwd=<GT>, so a relative --out/--project
    # would resolve under Graph-Tipper instead of here (and the bundle copy would miss).
    experiment = Path(experiment).resolve()
    project = Path(project).resolve()
    out = Path(out).resolve() if out else experiment / "runs" / "augment-pool"
    out.mkdir(parents=True, exist_ok=True)
    cmd = ["python3", "-m", "harness.kgpool.make",
           "--project", str(project), "--target", target, "--out", str(out)]
    if not jacoco:                       # JaCoCo is not used by the bundle; skip by default
        cmd.append("--skip-jacoco")
    for it in (tests or []):
        cmd += ["--tests", it]
    if spec_tests:
        cmd += ["--spec-tests", spec_tests]
    env = dict(os.environ, PYTHONPATH=str(gt))
    subprocess.run(cmd, cwd=str(gt), env=env, check=True)

    bundle = out / "augment.prompt.md"
    dst = experiment / "slices" / "augment.prompt.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(bundle, dst)
    print(f"bundle → {dst}\nNext: run it through a model → slices/forced-instrument-in-test.md, "
          "then set experiment.yaml augmentation: to that file.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--experiment", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--tests", action="append")
    ap.add_argument("--spec-tests", default=None)
    ap.add_argument("--jacoco", action="store_true",
                    help="also run the JaCoCo stage (needs jacocoagent + jacoco-cli jars); "
                         "off by default — the bundle does not use JaCoCo output")
    args = ap.parse_args()
    run(project=args.project, target=args.target, experiment=args.experiment,
        out=args.out, tests=args.tests, spec_tests=args.spec_tests, jacoco=args.jacoco)


if __name__ == "__main__":
    main()
