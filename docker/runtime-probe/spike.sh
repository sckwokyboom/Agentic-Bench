#!/usr/bin/env bash
# Runtime-probe spike (Plan 1, Task 6) — the GO/NO-GO gate.
#
# Instruments putValue, runs ONE covering test under the probe in the sandbox,
# and prints the capture. The test FAILS (the stub putValue throws) — that's
# expected; we only need the capture (entry stack + args, exit throw).
#
# Usage (from repo root, after building the image):
#   docker build -t abench-sandbox:latest -f docker/Dockerfile.sandbox .
#   bash docker/runtime-probe/spike.sh                       # default test
#   bash docker/runtime-probe/spike.sh picocli.HelpTest.testDemoUsage   # override
set -uo pipefail

FIXTURE="$(pwd)/experiments/picocli-putValue/stripped"
TEST="${1:-picocli.HelpTest.testCatUsageFormat}"   # a putValue-covering test
TARGET='picocli.CommandLine$Help$TextTable.putValue'
IMAGE="${IMAGE:-abench-sandbox:latest}"

if [ ! -d "$FIXTURE" ]; then
  echo "[spike] fixture not found: $FIXTURE (run from the repo root)" >&2
  exit 2
fi

echo "[spike] image=$IMAGE  target=$TARGET  test=$TEST"
rm -f "$FIXTURE/.runtime-capture.jsonl"

# Attach via JAVA_TOOL_OPTIONS (env-based → the forked Test JVM reads it; the
# gradle --init-script path proved unreliable for reaching the fork).
docker run --rm -v "$FIXTURE:/work" -w /work \
  -e JAVA_TOOL_OPTIONS="-javaagent:/opt/runtime-probe/agent.jar=$TARGET -Druntime.probe.out=/work/.runtime-capture.jsonl" \
  --entrypoint bash "$IMAGE" -lc \
  "./gradlew :test --tests '$TEST' --continue -Dorg.gradle.daemon=false || true"

echo "==================== CAPTURE ===================="
if [ -s "$FIXTURE/.runtime-capture.jsonl" ]; then
  wc -l "$FIXTURE/.runtime-capture.jsonl"
  head -20 "$FIXTURE/.runtime-capture.jsonl"
  echo
  echo "[spike] GO check — above, do you see: (1) a real test -> ... -> putValue"
  echo "        stack, and (2) readable args? If yes -> GO (I write Plan 2)."
else
  echo "[spike] NO capture written. The -javaagent likely didn't reach the forked"
  echo "        Test JVM. NO-GO path — try the fallbacks in the plan (Task 6 Step 3):"
  echo "          - confirm the init-script is applied (Test task jvmArgs),"
  echo "          - or fall back to JAVA_TOOL_OPTIONS=-javaagent:\$RUNTIME_PROBE_JAR=\$RUNTIME_PROBE_TARGETS"
fi
