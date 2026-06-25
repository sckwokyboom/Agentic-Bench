#!/usr/bin/env bash
# Runtime-probe spike — the GO/NO-GO gate.
#
#   MODE=single : Plan-1 gate. Self-contained ProbeAdvice on the target → one
#                 capture line {method,args,stack}+{throw}. (Byte Buddy app-only.)
#   MODE=chain  : enriched-corridor gate (default). Bootstrap Recorder + CorridorAdvice
#                 on the allowlist → a corridor dump with per-frame args + exit
#                 returns/throw. De-risks: bootstrap shadow-stack reachable from
#                 advice inlined into picocli classes, with NO Byte Buddy on bootstrap.
#
# The test FAILS (the stub putValue throws) — expected; we only need the capture.
#
# Usage (from repo root, after building the image):
#   docker build -t abench-sandbox:latest -f docker/Dockerfile.sandbox .
#   bash docker/runtime-probe/spike.sh                            # chain mode, default test
#   MODE=single bash docker/runtime-probe/spike.sh                # Plan-1 single-target gate
#   bash docker/runtime-probe/spike.sh picocli.HelpTest.testDemoUsage   # override test
set -uo pipefail

FIXTURE="$(pwd)/experiments/picocli-putValue/stripped"
TEST="${1:-picocli.HelpTest.testCatUsageFormat}"   # a putValue-covering test
MODE="${MODE:-chain}"
IMAGE="${IMAGE:-abench-sandbox:latest}"

# Single-quoted so $Help / $TextTable stay literal (not shell-expanded).
TARGET='picocli.CommandLine$Help$TextTable.putValue'
# Chain allowlist = the observed putValue corridor (Plan-1 capture): target + its callers.
ALLOWLIST='picocli.CommandLine$Help$TextTable.putValue,picocli.CommandLine$Help$TextTable.addRowValues,picocli.CommandLine$Help.join,picocli.CommandLine.usage'

if [ ! -d "$FIXTURE" ]; then
  echo "[spike] fixture not found: $FIXTURE (run from the repo root)" >&2
  exit 2
fi

if [ "$MODE" = chain ]; then
  JTO="-Xbootclasspath/a:/opt/runtime-probe/recorder.jar -javaagent:/opt/runtime-probe/agent.jar=$ALLOWLIST -Druntime.probe.mode=chain -Druntime.probe.targets=$TARGET -Druntime.probe.out=/work/.runtime-capture.jsonl"
else
  JTO="-javaagent:/opt/runtime-probe/agent.jar=$TARGET -Druntime.probe.out=/work/.runtime-capture.jsonl"
fi

echo "[spike] image=$IMAGE  mode=$MODE  test=$TEST"
echo "[spike] JAVA_TOOL_OPTIONS=$JTO"
rm -f "$FIXTURE/.runtime-capture.jsonl"

docker run --rm -v "$FIXTURE:/work" -w /work \
  -e JAVA_TOOL_OPTIONS="$JTO" \
  --entrypoint bash "$IMAGE" -lc \
  "./gradlew :test --tests '$TEST' --continue -Dorg.gradle.daemon=false || true"

echo "==================== CAPTURE ===================="
if [ -s "$FIXTURE/.runtime-capture.jsonl" ]; then
  wc -l "$FIXTURE/.runtime-capture.jsonl"
  head -40 "$FIXTURE/.runtime-capture.jsonl"
  echo
  if [ "$MODE" = chain ]; then
    echo "[spike] GO check (chain) — above, do you see:"
    echo "        (1) a {\"corridor\":[...]} dump with per-frame args for putValue,"
    echo "            addRowValues, join, usage (each frame its own runtime args),"
    echo "        (2) exit events with the target throw + at least one enclosing ret,"
    echo "        (3) NO LinkageError / NoClassDefFoundError / verifier error above?"
    echo "        If yes → GO (host pipeline + phased-runtime-chain)."
  else
    echo "[spike] GO check (single) — a real test → … → putValue stack + readable args?"
  fi
else
  echo "[spike] NO capture written. NO-GO path:"
  echo "        - chain: check stderr for '[probe] premain mode=chain', LinkageError,"
  echo "          or NoClassDefFoundError abench/probe/rt/Recorder (bootclasspath miss);"
  echo "        - confirm '-Xbootclasspath/a:/opt/runtime-probe/recorder.jar' reached the fork"
  echo "          ('Picked up JAVA_TOOL_OPTIONS' under '> Task :test')."
fi
