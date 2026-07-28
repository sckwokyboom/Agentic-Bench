#!/usr/bin/env python3
"""Generate the Defects4J COST-TO-SOLVE A/B: baseline vs phased vs rcc.

The sieve settled the solve-rate question — plain opencode+deepseek fixes 45/46
Defects4J bugs, so "can the agent do it" is not the interesting axis. What the runs
DID expose is how expensive some solves are: Closure-116 took 135 steps, 236k tokens
and 26 minutes. This A/B measures that cost, where 45 solved bugs give far more
statistical power than one hard bug.

Per bug it emits an experiment whose arms all run over the SAME fixture, which abench
interleaves and nonce-isolates within one run:
  baseline — plain agent, no orchestration
  phased   — forced UNDERSTAND→IMPLEMENT→DIAGNOSE controller (optional)
  rcc      — the same prefix, then the causal loop (MutationGraph/Alpha/Beta/Gamma)

Default arms are **baseline,rcc** — the product comparison ("our system vs a plain
agent"). Mind what that measures: the orchestrated arms are handed the target method
(target_label/target_file) and baseline is not, so an rcc-vs-baseline gap contains
both the causal loop AND the target hint. `--arms baseline,phased,rcc` adds the
control that isolates the loop alone (phased gets the same target info as rcc), and
`--tell-baseline-target` instead hands the same hint to baseline so the arms differ
only by machinery.

TARGET RESOLUTION: rcc needs the target method to seed its mutation graph, and
gems.csv's method_hint is a class declaration, not a method. The method is derived
offline from the GROUND-TRUTH diff (checkout vs reference) — the same value for both
orchestrated arms, so it cannot bias rcc vs phased.

GRADING NOTE: the arms are NOT given restore_non_target_before_verify, so each run
reflects natural agent behaviour (including build-fighting). Verdicts must therefore
be re-derived environment-independently afterwards with d4j_replay.py — the sieve
proved a workdir-graded verdict can be about a fabricated dependency stub rather
than the code (Time-14).

    python3 scripts/d4j_ab.py                    # default 12-bug expensive set, 1 rep
    python3 scripts/d4j_ab.py --reps 2           # 2 reps (recommended for variance)
    python3 scripts/d4j_ab.py --bugs Closure-49,Time-6
"""
from __future__ import annotations

import argparse
import csv
import difflib
import re
from pathlib import Path

MODEL = "deepseek/deepseek-v4-flash"

#: The expensive solves from the sieve — steps/tokens/seconds the plain agent burned.
#: These are where a cycle-time win is measurable at all; a 100-second bug has no
#: room to show one.
DEFAULT_SET = ["Closure-116", "Closure-175", "JacksonDatabind-18", "Closure-49",
               "Time-24", "Time-6", "Mockito-3", "Closure-86", "Closure-29",
               "JacksonXml-6", "Math-102", "JacksonDatabind-63"]

#: A Java method/constructor signature. Deliberately loose on modifiers and generics,
#: strict on the '(' — enough to name the enclosing method of a changed line.
_SIG = re.compile(
    r"^\s*(?:@\w+[^\n]*\s+)?(?:public|protected|private|static|final|abstract|"
    r"synchronized|native|strictfp|\s)*[\w<>\[\],.?\s]+\s+(\w+)\s*\([^;]*$")
_SKIP = {"if", "for", "while", "switch", "catch", "return", "new", "else", "do"}

EXPERIMENT = """\
# AUTO-GENERATED cost-to-solve A/B for Defects4J {proj}-{bug}
# {triggers} triggering tests | target {cls}
# Baseline sieve cost for reference: see experiments/defects4j/README.md
name: d4j-{proj}-{bug}-ab
fixture_path: ./checkout           # buggy tree
reference_path: ./reference        # fixed tree (target_similarity)
task_prompt: {task}
system_prompt: ../system.md
model: {model}
repetitions: {reps}
output_dir: ./runs-ab
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
  rcc_revert_to_best: true         # part of the rcc STRATEGY (see config docs)
conditions:
{conditions}
# rcc builds its MutationGraph with the LLM builder here (no precomputed GT artifact
# is shipped for Defects4J) — runner falls back to 'llm' when .impact is absent.
target_file: {target_file}
target_methods: [{methods}]
verify:
  command: "defects4j test"
  timeout_s: 1800
metrics:
  test_command_patterns:
    - "defects4j( |$)"
    - "(mvn|mvnw|ant|gradlew)( |$)"
"""


def find_class_file(tree: Path, class_fqn: str) -> Path | None:
    """The .java file for a fully-qualified class, wherever the project puts it
    (Defects4J layouts differ: src/, source/, src/main/java/, src/java/…)."""
    rel = class_fqn.replace(".", "/") + ".java"
    hits = [p for p in tree.rglob("*.java") if str(p).endswith(rel)]
    return hits[0] if hits else None


def methods_from_gt_diff(buggy: Path, fixed: Path) -> list[str]:
    """Names of the methods the GROUND-TRUTH fix touched.

    Ground truth is used only to POINT AT the method under repair — the same value
    goes to both orchestrated arms, so it cannot bias rcc vs phased. Nothing about
    the fix itself is passed on.
    """
    a = buggy.read_text(encoding="utf-8", errors="replace").splitlines()
    b = fixed.read_text(encoding="utf-8", errors="replace").splitlines()
    changed: set[int] = set()
    for tag, i1, i2, _, _ in difflib.SequenceMatcher(a=a, b=b).get_opcodes():
        if tag != "equal":
            changed.update(range(i1, min(i2 + 1, len(a))))
    names: list[str] = []
    for ln in sorted(changed):
        for j in range(ln, -1, -1):          # nearest signature above the change
            m = _SIG.match(a[j])
            if m and m.group(1) not in _SKIP:
                if m.group(1) not in names:
                    names.append(m.group(1))
                break
    return names


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gems", default="experiments/defects4j/gems.csv", type=Path)
    ap.add_argument("--root", default="d4j-runs", type=Path,
                    help="the sieve's run root (checkouts already live here)")
    ap.add_argument("--bugs", help="comma-separated bug ids (default: the expensive set)")
    ap.add_argument("--reps", type=int, default=1,
                    help="repetitions per condition; 2+ recommended (agents are high-variance)")
    ap.add_argument("--arms", default="baseline,rcc",
                    help="comma-separated arms: baseline, phased, rcc "
                         "(add phased to isolate the causal loop from the target hint)")
    ap.add_argument("--tell-baseline-target", action="store_true",
                    help="append the target method to the task prompt for ALL arms, so "
                         "baseline gets the same hint as rcc and the arms differ only "
                         "by machinery")
    a = ap.parse_args()

    arms = [s.strip() for s in a.arms.split(",") if s.strip()]
    unknown = [x for x in arms if x not in ("baseline", "phased", "rcc")]
    if unknown:
        print(f"unknown arm(s): {unknown}; choose from baseline, phased, rcc")
        return 2
    _ARM_YAML = {
        "baseline": "  - {name: baseline, augmentation: null, tools: []}",
        "phased": "  - {name: phased, orchestration: phased}       # control",
        "rcc": "  - {name: rcc, orchestration: rcc}             # treatment",
    }

    want = [s.strip() for s in a.bugs.split(",")] if a.bugs else DEFAULT_SET
    gems = {f"{r['project']}-{r['bug']}": r for r in csv.DictReader(a.gems.open())}
    lines = ["#!/usr/bin/env bash", "set -uo pipefail",
             "# Cost-to-solve A/B: baseline vs phased vs rcc. Resumable (see the guard).",
             'ROOT="$(cd "$(dirname "$0")" && pwd)"', ""]
    made, skipped = [], []

    for key in want:
        r = gems.get(key)
        d = a.root / key
        if r is None:
            skipped.append(f"{key}: not in gems.csv"); continue
        if not (d / "checkout").is_dir() or not (d / "reference").is_dir():
            skipped.append(f"{key}: needs both checkout/ and reference/ (run the sieve first)")
            continue
        src = find_class_file(d / "checkout", r["modified_class"])
        ref = find_class_file(d / "reference", r["modified_class"])
        if src is None:
            skipped.append(f"{key}: {r['modified_class']} not found in checkout"); continue
        methods = methods_from_gt_diff(src, ref) if ref else []
        if not methods:
            # No method resolved: rcc would seed its graph with an empty FQN, which
            # silently weakens the treatment arm. Skip loudly rather than run a
            # degraded arm and call it a fair comparison.
            skipped.append(f"{key}: could not resolve the target method from the GT diff")
            continue
        cls_short = r["modified_class"].rsplit(".", 1)[-1]
        task = "../task.md"
        if a.tell_baseline_target:
            # A per-bug prompt carrying the same hint the orchestrated arms get, so
            # baseline is not handicapped by having to locate the method first.
            (d / "task-ab.md").write_text(
                (a.root / "task.md").read_text(encoding="utf-8")
                + f"\nThe defect is in {r['modified_class']}#{methods[0]}. "
                  "Fix it there; do not edit the tests.\n", encoding="utf-8")
            task = "./task-ab.md"
        (d / "experiment-ab.yaml").write_text(EXPERIMENT.format(
            proj=r["project"], bug=r["bug"], triggers=r["triggers"],
            cls=r["modified_class"], model=MODEL, reps=a.reps, task=task,
            label=f"the {cls_short}.{methods[0]} method",
            conditions="\n".join(_ARM_YAML[x] for x in arms),
            target_file=str(src.relative_to(d / "checkout")),
            methods=", ".join(methods[:4])))
        made.append((key, str(src.relative_to(d / "checkout")), methods[:4]))
        lines += [
            f'echo "=== {key} (A/B: {"|".join(arms)}) ==="',
            f'D="$ROOT/{key}"',
            'if ls "$D"/runs-ab/*/*/*/rep_*/metrics.json >/dev/null 2>&1; then',
            f'  echo "  SKIP {key}: already has A/B runs (rm -rf $D/runs-ab to redo)"',
            "else",
            f'  ( cd "$D" && abench run experiment-ab.yaml ) || echo "  !! A/B failed: {key}"',
            "fi",
            "",
        ]

    script = a.root / "run_ab.sh"
    script.write_text("\n".join(lines))
    script.chmod(0o755)
    print(f"generated {len(made)} A/B experiments (reps={a.reps}) + {script}")
    for k, f, m in made:
        print(f"  {k:22} target={f}  methods={m}")
    if skipped:
        print("\nSKIPPED:")
        for s in skipped:
            print(f"  {s}")
    print(f"\nArms: {arms}"
          + ("  [baseline also told the target]" if a.tell_baseline_target else ""))
    print(f"Runs: {len(made)} bugs x {len(arms)} arms x {a.reps} rep(s) = "
          f"{len(made) * len(arms) * a.reps} agent sessions.")
    print("After the batch, re-grade every arm environment-independently:")
    print("  python3 scripts/d4j_replay.py --ab --out replay-ab.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
