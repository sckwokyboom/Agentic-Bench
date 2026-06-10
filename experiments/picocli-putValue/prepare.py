# experiments/picocli-putValue/prepare.py
"""Prepare the picocli-putValue experiment end-to-end on a fresh machine.

Stages: deps -> fixtures -> artifacts -> overlay -> smoke.
  python prepare.py [--only STAGE] [--force]
Needs: activated venv, GRAPH_TIPPER_HOME env, JDK 17-21, opencode 1.15.x.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCK = dict(line.split("=", 1) for line in
            (HERE / "fixture.lock").read_text().strip().splitlines())
GT = os.environ.get("GRAPH_TIPPER_HOME")
TARGET_FQN = "picocli.CommandLine$Help$TextTable.putValue"
SLICE_TARGET = "src/main/java/picocli/CommandLine.java#TextTable.putValue(int,int,Text)"
CAPTURE_TESTS = "picocli.HelpTest,picocli.TextTableTest"


def run(cmd, cwd=HERE, env=None):
    print(f"[prepare] $ {' '.join(map(str, cmd))}")
    e = dict(os.environ)
    if env:
        e.update(env)
    subprocess.run([str(c) for c in cmd], cwd=str(cwd), env=e, check=True)


def s_deps(force):
    missing = []
    if GT is None or not (Path(GT) / "harness" / "impact").is_dir():
        missing.append("GRAPH_TIPPER_HOME must point at a Graph-Tipper checkout "
                       "(git clone https://github.com/<you>/Graph-Tipper)")
    if shutil.which("opencode") is None:
        missing.append("opencode: npm i -g opencode-ai")
    if shutil.which("git") is None:
        missing.append("git")
    if missing:
        sys.exit("[prepare:deps] missing:\n- " + "\n- ".join(missing))
    print("[prepare:deps] ok (run scripts/setup_check.py for the full matrix)")


def s_fixtures(force):
    orig, stripped = HERE / "original", HERE / "stripped"
    if orig.exists() and not force:
        print("[prepare:fixtures] original/ exists, skip (use --force to redo)")
    else:
        shutil.rmtree(orig, ignore_errors=True)
        run(["git", "-c", "core.autocrlf=false", "clone", LOCK["repo"], orig])
        run(["git", "checkout", "-q", LOCK["sha"]], cwd=orig)
        shutil.rmtree(orig / ".git")
    if stripped.exists() and not force:
        print("[prepare:fixtures] stripped/ exists, skip")
        return
    shutil.rmtree(stripped, ignore_errors=True)
    shutil.copytree(orig, stripped)
    run([sys.executable, HERE / "strip_target.py",
         "--file", stripped / LOCK["file"],
         "--signature", LOCK["signature"], "--stub", LOCK["stub"]])
    gw = "gradlew.bat" if os.name == "nt" else "./gradlew"
    run([gw, "compileJava", "-q", "--console=plain"], cwd=stripped)


def s_artifacts(force):
    out = HERE / "gt-out"
    run([sys.executable, "-m", "harness.impact.produce_artifacts",
         "--project", HERE / "original", "--target-fqn", TARGET_FQN,
         "--slice-target", SLICE_TARGET, "--tests", CAPTURE_TESTS,
         "--out", out, *(["--force"] if force else [])],
        cwd=GT, env={"PYTHONPATH": GT})
    for name in ("putValue-graph-slice.md", "putValue-graph-slice-verbose.md"):
        fresh = (out / "slices" / name).read_text(encoding="utf-8")
        committed = HERE / "slices" / name
        if committed.exists() and committed.read_text(encoding="utf-8") != fresh:
            diff = "".join(difflib.unified_diff(
                committed.read_text(encoding="utf-8").splitlines(True), fresh.splitlines(True),
                f"committed/{name}", f"fresh/{name}"))[:2000]
            print(f"[prepare:artifacts] WARNING: drift vs committed {name}:\n{diff}")
        committed.write_text(fresh, encoding="utf-8")
    impact_dst = HERE / "overlays" / "impact" / ".impact"
    shutil.rmtree(impact_dst, ignore_errors=True)
    shutil.copytree(out / "impact", impact_dst)
    universe = impact_dst / "executed_tests.txt"
    tmpl = json.loads((HERE / "overlays" / "impact" / ".opencode" / "impact.json.tmpl")
                      .read_text(encoding="utf-8").replace("${GRAPH_TIPPER_HOME}", "/x"))
    n = len(universe.read_text(encoding="utf-8").strip().splitlines())
    if n != tmpl["total_tests"]:
        print(f"[prepare:artifacts] WARNING: total_tests in tmpl={tmpl['total_tests']} "
              f"vs executed universe={n} — update the tmpl")


def s_overlay(force):
    src = Path(GT) / "integrations" / "opencode" / "tools" / "impact.ts"
    dst = HERE / "overlays" / "impact" / ".opencode" / "tools" / "impact.ts"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"[prepare:overlay] copied {src.name} from GRAPH_TIPPER_HOME")


def s_smoke(force):
    sys.path.insert(0, str(HERE.parents[1]))
    from abench.config import load_experiment
    load_experiment(HERE / "experiment.yaml")
    print("[prepare:smoke] experiment.yaml loads & validates")
    r = subprocess.run(["opencode", "run", "-m", "opencode/deepseek-v4-flash-free",
                        "Reply with exactly: OK"], capture_output=True, text=True,
                       timeout=120)
    print("[prepare:smoke] model ping:", "ok" if "OK" in r.stdout else f"CHECK AUTH\n{r.stdout[-300:]}")


STAGES = [("deps", s_deps), ("fixtures", s_fixtures), ("artifacts", s_artifacts),
          ("overlay", s_overlay), ("smoke", s_smoke)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, choices=[n for n, _ in STAGES])
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    for name, fn in STAGES:
        if a.only and name != a.only:
            continue
        print(f"[prepare] ── {name}")
        fn(a.force)
    print("[prepare] done. Next: abench run experiments/picocli-putValue/experiment.yaml")


if __name__ == "__main__":
    main()
