# experiments/picocli-putValue/prepare.py
"""Prepare the picocli-putValue experiment end-to-end on a fresh machine.

Stages: deps -> fixtures -> artifacts -> smoke.
  python prepare.py [--only STAGE] [--force]
Needs: activated venv, Graph-Tipper registered (abench lib add graph-tipper <path>)
or GRAPH_TIPPER_HOME env, JDK 21+, opencode 1.15.x.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCK = dict(line.split("=", 1) for line in
            (HERE / "fixture.lock").read_text().strip().splitlines())
def _resolve_gt():
    """GT host path: local registry ('graph-tipper') first, then GRAPH_TIPPER_HOME."""
    try:
        from abench.libraries import load_registry
        p = load_registry().get("graph-tipper")
        if p:
            return p
    except Exception:
        pass
    return os.environ.get("GRAPH_TIPPER_HOME")


GT = _resolve_gt()
TARGET_FQN = "picocli.CommandLine$Help$TextTable.putValue"
SLICE_TARGET = "src/main/java/picocli/CommandLine.java#TextTable.putValue(int,int,Text)"
CAPTURE_TESTS = "picocli.HelpTest,picocli.TextTableTest"


def _rmtree(path: Path) -> None:
    """rmtree that survives read-only files (git objects on Windows)."""
    def _force(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    if not Path(path).exists():
        return
    kw = {"onexc": _force} if sys.version_info >= (3, 12) else {"onerror": _force}
    shutil.rmtree(path, **kw)


def run(cmd, cwd=HERE, env=None):
    print(f"[prepare] $ {' '.join(map(str, cmd))}")
    e = dict(os.environ)
    if env:
        e.update(env)
    subprocess.run([str(c) for c in cmd], cwd=str(cwd), env=e, check=True)


def s_deps(force):
    missing = []
    if GT is None or not (Path(GT) / "harness" / "impact").is_dir():
        missing.append("Graph-Tipper path not found — set it with "
                       "`abench lib add graph-tipper <path>` or GRAPH_TIPPER_HOME")
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
        _rmtree(orig)
        run(["git", "-c", "core.autocrlf=false", "clone", LOCK["repo"], orig])
        run(["git", "checkout", "-q", LOCK["sha"]], cwd=orig)
        _rmtree(orig / ".git")
    if stripped.exists() and not force:
        print("[prepare:fixtures] stripped/ exists, skip")
        return
    _rmtree(stripped)
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
         # graph context comes from the full tree; the artifact's "Current
         # body" must show the agent-visible stub — the full body is the answer.
         "--out", out, "--body-from", HERE / "stripped",
         *(["--force"] if force else [])],
        cwd=GT, env={"PYTHONPATH": GT})
    for name in ("putValue-graph-slice.md", "putValue-graph-slice-verbose.md"):
        fresh = (out / "slices" / name).read_text(encoding="utf-8")
        if 'UnsupportedOperationException("TODO' not in fresh:
            sys.exit(f"[prepare:artifacts] LEAK GUARD: {name} does not show the "
                     "stub body — refusing to publish a slice that may contain "
                     "the reference solution")
        committed = HERE / "slices" / name
        committed_text = committed.read_text(encoding="utf-8") if committed.exists() else None
        if committed_text != fresh:
            if committed_text is not None:
                diff = "".join(difflib.unified_diff(
                    committed_text.splitlines(True), fresh.splitlines(True),
                    f"committed/{name}", f"fresh/{name}"))[:2000]
                print(f"[prepare:artifacts] WARNING: drift vs committed {name}:\n{diff}")
            committed.write_text(fresh, encoding="utf-8")
    impact_dst = HERE / "overlays" / "impact-artifacts" / ".impact"
    _rmtree(impact_dst)
    shutil.copytree(out / "impact", impact_dst)
    universe = impact_dst / "executed_tests.txt"
    n = len(universe.read_text(encoding="utf-8").strip().splitlines())
    cfg = json.loads((HERE / "overlays" / "impact-artifacts" / ".opencode" / "impact.json")
                     .read_text(encoding="utf-8"))
    if n != cfg["total_tests"]:
        print(f"[prepare:artifacts] WARNING: total_tests in impact.json={cfg['total_tests']} "
              f"but executed universe has {n} tests")


def s_smoke(force):
    sys.path.insert(0, str(HERE.parents[1]))
    from abench.config import load_experiment
    load_experiment(HERE / "experiment.yaml")
    print("[prepare:smoke] experiment.yaml loads & validates")
    try:
        r = subprocess.run(["opencode", "run", "-m", "opencode/deepseek-v4-flash-free",
                            "Reply with exactly: OK"], capture_output=True, text=True,
                           timeout=120)
    except subprocess.TimeoutExpired:
        print("[prepare:smoke] model ping: TIMEOUT (120s) — check opencode auth / network")
        return
    print("[prepare:smoke] model ping:", "ok" if "OK" in r.stdout else f"CHECK AUTH\n{r.stdout[-300:]}")


STAGES = [("deps", s_deps), ("fixtures", s_fixtures), ("artifacts", s_artifacts),
          ("smoke", s_smoke)]


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
