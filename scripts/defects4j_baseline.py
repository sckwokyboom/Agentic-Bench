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
    mode: none                     # host mode for the sieve (no docker); JDK per project
conditions:
  - {{name: baseline, augmentation: null, tools: []}}   # pure agent, NO augmentation
target_file: {target_file}
target_methods: [{method}]         # from metadata; baseline ignores, rcc/phased use later
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


def _class_to_path(fqn: str) -> str:
    # best-effort src path; the agent/verify don't depend on it (rcc/phased do).
    return "src/main/java/" + fqn.replace(".", "/") + ".java" if fqn else ""


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
        "# Preflight: the Defects4J framework itself requires Java 11 (not 8).",
        'if defects4j info -p Lang -b 1 2>&1 | grep -q "Java 11 is required"; then',
        '  echo "!! Defects4J needs Java 11 to run. Point JAVA_HOME/PATH at a JDK 11:"',
        '  echo "   sudo apt install -y openjdk-11-jdk   # Debian/Ubuntu/WSL"',
        r'  echo "   export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64; export PATH=\$JAVA_HOME/bin:\$PATH"',
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
            model=MODEL, target_file=_class_to_path(r["modified_class"]),
            method=r["modified_class"].split(".")[-1]))  # class as target hint
        lines += [
            f'echo "=== {P}-{bug} ({r["triggers"]} triggers, {r["tier"]}) ==="',
            f'D="$ROOT/{P}-{bug}"',
            # Only run abench if the buggy checkout actually materialised — a failed
            # checkout must NOT cascade into abench's fixture-not-found error.
            f'if defects4j checkout -p {P} -v {bug}b -w "$D/checkout" && [ -d "$D/checkout" ]; then',
            f'  defects4j checkout -p {P} -v {bug}f -w "$D/reference" || true',
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
