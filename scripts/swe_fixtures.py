#!/usr/bin/env python3
"""Turn native Multi-SWE-bench (Java) records into fixture-mode A/B experiments.

Benchmark mode cannot run rcc (bench/run.py drives the agent directly and config
validation now refuses an orchestrated condition there), and the official evaluator
needs Docker + the pinned harness. Fixture mode already runs rcc, so this builds the
same kind of self-contained fixture the Defects4J A/B used, straight from the dataset:

    checkout/   = repo @ base.sha  +  test_patch      -> the new tests FAIL
    reference/  = repo @ base.sha  +  test_patch + fix_patch  -> they pass

The agent sees only checkout/ and the issue text. `fix_patch` is used solely to build
the reference tree and to POINT AT the method under repair (identical value for both
arms, so it cannot bias rcc vs baseline) — never shown to the agent.

WHAT THIS IS NOT: the verdict is our own test run, not the official multi-swe-bench
`resolved`. These numbers are comparable to our Defects4J A/B and to each other; they
are NOT comparable to published SWE-bench scores. For that, the official path
(orchestration in benchmark mode + the container evaluator) is required.

    python3 scripts/swe_fixtures.py ~/msb-data/jackson-core.jsonl --limit 6
    bash swe-runs/run_swe.sh
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from d4j_ab import methods_from_gt_diff  # noqa: E402

from abench.bench.swebench_java import _BUILD_SYSTEM, _is_test_path  # noqa: E402

MODEL = "deepseek/deepseek-v4-flash"

#: Full suite, not just the fail-to-pass tests: a fix that breaks something else must
#: show up. Quiet/batch flags keep the log readable.
_VERIFY = {"maven": "mvn -B -q test", "gradle": "./gradlew test --continue"}

EXPERIMENT = """\
# AUTO-GENERATED from Multi-SWE-bench {iid}
# Fixture built as: repo@{sha} + test_patch (failing) ; reference adds fix_patch.
# NOTE: graded by OUR test run — not the official multi-swe-bench `resolved`.
name: swe-{slug}
fixture_path: ./checkout
reference_path: ./reference
task_prompt: ./task.md
system_prompt: ../system.md
model: {model}
repetitions: {reps}
output_dir: ./runs
opencode:
  agent: abench
  providers:
    - id: deepseek
      name: DeepSeek API
      base_url: https://api.deepseek.com/v1
      models: [deepseek-v4-flash, deepseek-chat, deepseek-reasoner]
      api_key_env: DEEPSEEK_API_KEY
  sandbox:
    mode: none
orchestration:
  target_label: {label}
  max_diagnose_iters: 8
  no_progress_limit: 2
  cluster_cap: 5
  rcc_max_attempts: 2
  rcc_subset_class_cap: 15
  rcc_revert_to_best: true
conditions:
  - {{name: baseline, augmentation: null, tools: []}}
  - {{name: rcc, orchestration: rcc}}
target_file: {target_file}
target_methods: [{methods}]
verify:
  command: "{verify}"
  timeout_s: 3600
metrics:
  test_command_patterns:
    - "(mvn|mvnw|gradlew|ant)( |$)"
"""

SYSTEM = """\
You are a senior Java engineer fixing a real bug reported in a project's issue
tracker. Read the code and the failing tests, localize the root cause, and make a
minimal source fix. Do not modify test files.
"""

TASK = """\
{issue}

---
Some of this project's tests currently FAIL because of the defect described above.
Fix the SOURCE code so the whole test suite passes. Do not edit the tests.
"""


def _sh(cmd: list[str], cwd: Path | None = None, check: bool = True) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True,
                       encoding="utf-8", errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    if check and p.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:3])}… failed ({p.returncode}): {out[-400:]}")
    return p.returncode, out


def _apply(patch: str, tree: Path) -> None:
    """Apply a unified diff, preferring git apply and falling back to patch(1)."""
    # Absolute: both tools run with cwd=tree, so a path relative to OUR cwd breaks.
    pf = (tree / ".apply.patch").resolve()
    pf.write_text(patch, encoding="utf-8")
    rc, out = _sh(["git", "apply", "--whitespace=nowarn", str(pf)], cwd=tree, check=False)
    if rc != 0:
        rc, out2 = _sh(["patch", "-p1", "--forward", "-i", str(pf)], cwd=tree, check=False)
        if rc != 0:
            raise RuntimeError(f"patch did not apply: {out[-300:]} | {out2[-300:]}")
    pf.unlink(missing_ok=True)


def _clone_at(url: str, sha: str, dest: Path) -> None:
    """Repo at an exact commit. Partial clone keeps it light on big repos; a full
    history is still fetched because base.sha is usually not a branch tip."""
    _sh(["git", "clone", "--filter=blob:none", "--no-checkout", url, str(dest)])
    _sh(["git", "checkout", "--detach", sha], cwd=dest)


def _patch_paths(patch: str) -> list[str]:
    """Repo-relative paths a unified diff touches (destination side)."""
    return [ln.split(" b/", 1)[1].strip().strip('"')
            for ln in patch.splitlines()
            if ln.startswith("diff --git ") and " b/" in ln]


def primary_source_file(patch: str) -> str | None:
    """The JAVA source file the gold fix changes most.

    Real SWE-bench fixes carry non-code companions — jackson's fix_patch leads with
    `release-notes/VERSION-2.x`, which is neither a test nor code, and taking the
    first path made a changelog the rcc target. Restrict to .java non-test files and
    rank by how many lines the fix actually changes there.
    """
    weights: dict[str, int] = {}
    path: str | None = None
    for line in patch.splitlines():
        if line.startswith("diff --git ") and " b/" in line:
            p = line.split(" b/", 1)[1].strip().strip('"')
            path = p if (p.endswith(".java") and not _is_test_path(p)) else None
            if path:
                weights.setdefault(path, 0)
        elif path and line[:1] in "+-" and not line.startswith(("+++", "---")):
            weights[path] += 1
    return max(weights, key=lambda k: weights[k]) if weights else None


def build(rec: dict, root: Path, reps: int, force: bool) -> tuple[str, str] | None:
    org, repo, num = rec["org"], rec["repo"], rec["number"]
    iid, slug = f"{org}/{repo}:pr-{num}", f"{org}_{repo}_pr{num}"
    d = root / slug
    if (d / "experiment.yaml").is_file() and not force:
        print(f"  = {iid}: already built (use --force to rebuild)")
        return None
    sha = (rec.get("base") or {}).get("sha") or ""
    test_patch, fix_patch = rec.get("test_patch") or "", rec.get("fix_patch") or ""
    if not (sha and test_patch and fix_patch):
        print(f"  ! {iid}: record lacks base.sha / test_patch / fix_patch — skipped")
        return None

    d.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/{org}/{repo}.git"
    for name, patches in (("checkout", [test_patch]),
                          ("reference", [test_patch, fix_patch])):
        tree = d / name
        if tree.is_dir():
            continue
        print(f"  … {iid}: building {name}")
        _clone_at(url, sha, tree)
        for p in patches:
            _apply(p, tree)

    # Target = the JAVA source file the GOLD fix changes most.
    target = primary_source_file(fix_patch)
    if target is None:
        print(f"  ! {iid}: fix_patch changes no .java source file — skipped")
        return None
    methods = methods_from_gt_diff(d / "checkout" / target, d / "reference" / target)
    if not methods:
        # rcc would seed its graph with an empty target and silently run weakened.
        print(f"  ! {iid}: could not resolve the target method in {target} — skipped")
        return None

    build_system = _detect_build_system(d / "checkout", f"{org}/{repo}")
    (d / "task.md").write_text(TASK.format(issue=_issue_text(rec)), encoding="utf-8")
    (d / "experiment.yaml").write_text(EXPERIMENT.format(
        iid=iid, slug=slug.replace("_", "-"), sha=sha[:12], model=MODEL, reps=reps,
        label=f"the {Path(target).stem}.{methods[0]} method",
        target_file=target, methods=", ".join(methods[:4]),
        verify=_VERIFY[build_system]), encoding="utf-8")
    print(f"  + {iid}: target={target} methods={methods[:3]} build={build_system}")
    return slug, iid


def _detect_build_system(tree: Path, slug: str) -> str:
    """Read the build system off the checked-out tree, falling back to the adapter's
    per-repo map. Defaulting unknown repos to maven emitted `mvn test` for Gradle
    projects (mockito, jib) — a guaranteed verify failure that looks like the agent's
    fault. The tree is on disk by now, so just look."""
    if (tree / "pom.xml").is_file():
        return "maven"
    if any((tree / f).exists() for f in
           ("build.gradle", "build.gradle.kts", "gradlew", "settings.gradle")):
        return "gradle"
    return _BUILD_SYSTEM.get(slug, "maven")


def _issue_text(rec: dict) -> str:
    parts = []
    if rec.get("title"):
        parts.append(f"# {rec['title'].strip()}")
    if rec.get("body"):
        parts.append(rec["body"].strip())
    for iss in rec.get("resolved_issues") or []:
        t, b = (iss.get("title") or "").strip(), (iss.get("body") or "").strip()
        if t or b:
            parts.append(f"## {t}\n{b}".strip())
    return "\n\n".join(parts) or "(no issue text in the record)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", type=Path, help="native Multi-SWE-bench JSONL (java)")
    ap.add_argument("--root", default="swe-runs", type=Path)
    ap.add_argument("--limit", type=int, default=0, help="build at most N instances")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--force", action="store_true", help="rebuild existing fixtures")
    a = ap.parse_args()
    # Validate ONCE, up front. Without this a bad download surfaces as one cryptic
    # json error per line — a hundred messages that never name the cause.
    from swe_fetch import validate
    count, err = validate(a.dataset)
    if err:
        print(f"unusable dataset {a.dataset}:\n  {err}")
        print("\nExpected NATIVE Multi-SWE-bench records (org/repo/number/base.sha/"
              "test_patch/fix_patch).\nGet one with:  python3 scripts/swe_fetch.py "
              "jackson-core   (see --list for the other repos)")
        return 2
    print(f"dataset: {count} instance(s) in {a.dataset}")

    a.root.mkdir(parents=True, exist_ok=True)
    (a.root / "system.md").write_text(SYSTEM, encoding="utf-8")
    made = []
    for line in a.dataset.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        if a.limit and len(made) >= a.limit:
            break
        try:
            got = build(json.loads(line), a.root, a.reps, a.force)
        except Exception as exc:                       # one bad record must not stop the sweep
            print(f"  ! failed: {exc}")
            continue
        if got:
            made.append(got)

    lines = ["#!/usr/bin/env bash", "set -uo pipefail",
             "# SWE-bench-java (fixture mode) A/B: baseline vs rcc. Resumable.",
             'ROOT="$(cd "$(dirname "$0")" && pwd)"', ""]
    for slug, iid in made:
        lines += [
            f'echo "=== {iid} (baseline|rcc) ==="',
            f'D="$ROOT/{slug}"',
            'if ls "$D"/runs/*/*/*/rep_*/metrics.json >/dev/null 2>&1; then',
            f'  echo "  SKIP {iid}: already has runs (rm -rf $D/runs to redo)"',
            "else",
            f'  ( cd "$D" && abench run experiment.yaml ) || echo "  !! failed: {iid}"',
            "fi", "",
        ]
    script = a.root / "run_swe.sh"
    script.write_text("\n".join(lines))
    script.chmod(0o755)
    print(f"\nbuilt {len(made)} fixture(s) under {a.root}/ + {script}")
    print(f"Runs: {len(made)} instances x 2 arms x {a.reps} rep(s) = "
          f"{len(made) * 2 * a.reps} agent sessions.")
    print("Verdicts here are OUR test runs, not the official SWE-bench `resolved`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
