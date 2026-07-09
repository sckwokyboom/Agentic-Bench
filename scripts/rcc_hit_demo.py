#!/usr/bin/env python3
"""Memory Graph hit-rate demo: run the SAME rcc condition twice against ONE
persistent memory file and report hit rate + wall-time delta. Deliberately
separate from the A/B (which resets memory per rep) — this measures learning
across encounters, not condition contrast.

Usage (venv active, JDK 21, prepared picocli machine):
    python3 scripts/rcc_hit_demo.py experiments/picocli-putValue/experiment-mac-rcc-ab.yaml
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def newest_rcc_trace(exp_dir: Path, name: str) -> dict:
    root = exp_dir / "runs" / name
    batches = sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: d.name)
    trace = batches[-1] / "rcc" / "rep_1" / "trace.json"
    return json.loads(trace.read_text())


def summarize(trace: dict) -> dict:
    wall = None
    if trace.get("started_at") and trace.get("ended_at"):
        wall = trace["ended_at"] - trace["started_at"]
    return {"memory_hit": bool(trace.get("rcc_memory_hit")),
            "outcome": trace.get("orchestration_outcome"),
            "wall_s": wall,
            "suite_runs": trace.get("controller_test_runs"),
            "subset_runs": trace.get("rcc_subset_test_runs")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("experiment", help="experiment YAML with an 'rcc' condition")
    ap.add_argument("--memory", default=None,
                    help="persistent memory path (default: a temp file)")
    args = ap.parse_args()
    exp = Path(args.experiment).resolve()
    mem = args.memory or str(Path(tempfile.mkdtemp(prefix="rcc-mem-")) / "memory.json")
    env = dict(os.environ, ABENCH_RCC_MEMORY=mem)
    name = None
    runs = []
    for i in (1, 2):
        print(f"[hit-demo] run {i}/2 (memory: {mem}) …", flush=True)
        subprocess.run([sys.executable, "-m", "abench.cli", "run", str(exp)],
                       env=env, check=True)
        if name is None:
            import yaml
            name = yaml.safe_load(exp.read_text())["name"]
        runs.append(summarize(newest_rcc_trace(exp.parent, name)))
    r1, r2 = runs
    print(json.dumps({"run1": r1, "run2": r2}, indent=2))
    print(f"[hit-demo] hit rate on repeat: {1.0 if r2['memory_hit'] else 0.0}")
    if r1["wall_s"] and r2["wall_s"]:
        print(f"[hit-demo] cycle-time reduction: "
              f"{(1 - r2['wall_s'] / r1['wall_s']) * 100:.0f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
