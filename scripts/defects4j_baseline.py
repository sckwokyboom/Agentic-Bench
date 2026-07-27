#!/usr/bin/env python3
"""Turn gems.csv (frozen Defects4J shortlist) into per-bug Agentic-bench BASELINE
experiments + a run script. Generation is offline (just writes files); the actual
run needs Defects4J installed+init'd and opencode+deepseek on the box.

Per gem it writes  d4j-runs/<P>-<bug>/experiment.yaml  and a top-level
run_baseline.sh that, for each gem:
   1) defects4j checkout the BUGGY tree into <dir>/checkout   (fixture)
   2) defects4j checkout the FIXED tree into <dir>/reference  (for target_similarity)
   3) abench run <dir>/experiment.yaml   -> baseline (opencode+deepseek, NO aug/tools/orch)

GRADING (the one integration seam to VALIDATE first): verify runs `defects4j test`
in the workdir — Defects4J's authoritative relevant-test verdict. Confirm abench
grades its output on ONE gem before the batch (see runbook).
"""
from __future__ import annotations
import csv, sys
from pathlib import Path

MODEL = "deepseek/deepseek-v4-flash"

EXPERIMENT = """\
# AUTO-GENERATED baseline experiment for Defects4J {proj}-{bug}
# {triggers} triggering tests | modified class {cls}
name: d4j-{proj}-{bug}-baseline
fixture_path: ./checkout           # buggy tree: defects4j checkout -v {bug}b
reference_path: ./reference        # fixed tree: defects4j checkout -v {bug}f
task_prompt: ../task.md
system_prompt: ../system.md
model: {model}
repetitions: 1
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
    mode: none                     # host mode for the sieve (no docker); Java 11
conditions:
  - {{name: baseline, augmentation: null, tools: []}}   # pure agent, NO augmentation
# NOTE: no target_file here — the baseline sieve doesn't need it, and Defects4J
# source layouts vary per project ({cls} lives at a project-specific path). The
# rcc/phased arm sets the correct target_file per bug from the GT precompute.
verify:
  command: "defects4j test"        # Defects4J relevant-test grading (VALIDATE first)
  timeout_s: 1800
metrics:
  test_command_patterns:
    - "defects4j( |$)"
    - "(mvn|mvnw)( |$)"
"""

TASK = """\
This Java project has a bug: some of its tests currently FAIL. Find and fix the
defect in the SOURCE code so the whole relevant test suite passes. Do not edit the
tests. Run the tests to confirm (the harness grades with `defects4j test`).
"""

SYSTEM = """\
You are a senior Java engineer fixing a real bug in an existing project. Read the
code and the failing tests, localize the root cause, and make a minimal source fix.
Do not modify test files.
"""


def main() -> int:
    gems = Path(sys.argv[1] if len(sys.argv) > 1 else "gems.csv")
    only = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None  # e.g. nonlocal_gem
    root = Path("d4j-runs")
    root.mkdir(exist_ok=True)
    (root / "task.md").write_text(TASK)
    (root / "system.md").write_text(SYSTEM)
    rows = [r for r in csv.DictReader(gems.open())
            if only is None or r["tier"] in only]
    lines = [
        "#!/usr/bin/env bash",
        "set -uo pipefail",
        "# Prereqs: `defects4j` on PATH (the framework needs JAVA 11 to RUN);",
        "# `defects4j init` done; DEEPSEEK_API_KEY set; opencode 1.15.x with deepseek auth.",
        'ROOT="$(cd "$(dirname "$0")" && pwd)"',
        "",
        "# Preflight: Defects4J must be RUNNABLE (needs Java 11 + Perl deps + init).",
        'if ! defects4j info -p Lang -b 1 >/dev/null 2>&1; then',
        '  echo "!! defects4j is not runnable. Fix its setup, then re-run:"',
        r'  echo "   Java 11:   sudo apt install -y openjdk-11-jdk; export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64; export PATH=\$JAVA_HOME/bin:\$PATH"',
        '  echo "   Perl deps: sudo apt install -y cpanminus build-essential; sudo cpanm String::Interpolate DBI DBD::CSV JSON URI Text::CSV"',
        '  echo "   svn+git:   sudo apt install -y subversion git   # Chart & some projects are SVN-backed"',
        '  echo "   init:      (cd defects4j && ./init.sh)"',
        '  echo "   verify:    defects4j info -p Lang -b 1   # must print bug info"',
        "  exit 1",
        "fi",
        "",
    ]
    for r in rows:
        P, bug = r["project"], r["bug"]
        d = root / f"{P}-{bug}"
        d.mkdir(exist_ok=True)
        (d / "experiment.yaml").write_text(EXPERIMENT.format(
            proj=P, bug=bug, triggers=r["triggers"], cls=r["modified_class"],
            model=MODEL))
        lines += [
            f'echo "=== {P}-{bug} ({r["triggers"]} triggers, {r["tier"]}) ==="',
            f'D="$ROOT/{P}-{bug}"',
            # Run abench only if BOTH checkouts materialised — abench needs the buggy
            # fixture AND the fixed reference (target_similarity metric + _validate).
            # A failed checkout (e.g. missing svn) must not cascade into abench errors.
            f'if defects4j checkout -p {P} -v {bug}b -w "$D/checkout" \\',
            f'   && defects4j checkout -p {P} -v {bug}f -w "$D/reference" \\',
            '   && [ -d "$D/checkout" ] && [ -d "$D/reference" ]; then',
            f'  ( cd "$D" && abench run experiment.yaml ) || echo "  !! abench run failed: {P}-{bug}"',
            "else",
            f'  echo "  SKIP {P}-{bug}: defects4j checkout failed (see errors above)"',
            "fi",
            "",
        ]
    (root / "run_baseline.sh").write_text("\n".join(lines))
    (root / "run_baseline.sh").chmod(0o755)
    print(f"generated {len(rows)} experiments under {root}/ + run_baseline.sh")
    print("VALIDATE the `defects4j test` verify on ONE gem before the batch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
