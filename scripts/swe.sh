#!/usr/bin/env bash
# One entry point for the SWE-bench-java (fixture mode) A/B: baseline vs rcc.
#
#   ./scripts/swe.sh fetch  [repo…]      download + schema-validate datasets
#   ./scripts/swe.sh build  [--limit N]  clone@base.sha + patches -> fixtures + run script
#   ./scripts/swe.sh doctor [dir]        check toolchain; with a fixture dir, prove it builds
#   ./scripts/swe.sh run                 run the batch (resumable — Ctrl-C is safe)
#   ./scripts/swe.sh status              progress of a running batch (safe anytime)
#   ./scripts/swe.sh probe [repos…]      memorisation probe across repos -> probe.md
#   ./scripts/swe.sh logs  [roots…]      collect every FAILURE -> failures.md
#   ./scripts/swe.sh report              digest to swe-ab.md
#   ./scripts/swe.sh all                 fetch + build + doctor + run + report
#
# Env: DEEPSEEK_API_KEY (required to run), MSB_DATA (default ~/msb-data),
#      SWE_ROOT (default ./swe-runs), SWE_REPO (default jackson-core), SWE_LIMIT, SWE_REPS,
#      SWE_PROBE_REPOS (default 'fastjson2 logstash'),
#      SWE_PROBE_BASE  (where probe roots live; put it on the LINUX fs under WSL —
#                       a /mnt/* DrvFs tree throws Input/output error under git+maven).
#
# The verdicts produced here are OUR test runs, NOT the official multi-swe-bench
# `resolved` — comparable to our Defects4J A/B and to each other, not to published
# SWE-bench numbers.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
MSB_DATA="${MSB_DATA:-$HOME/msb-data}"
SWE_ROOT="${SWE_ROOT:-$ROOT/swe-runs}"
SWE_REPO="${SWE_REPO:-jackson-core}"
SWE_LIMIT="${SWE_LIMIT:-4}"
SWE_REPS="${SWE_REPS:-2}"
PY="${PYTHON:-python3}"

cmd="${1:-}"; shift || true

case "$cmd" in
  fetch)
    "$PY" "$HERE/swe_fetch.py" --out "$MSB_DATA" "${@:-$SWE_REPO}"
    ;;

  build)
    ds="$MSB_DATA/$SWE_REPO.jsonl"
    if [ ! -f "$ds" ]; then
      echo "dataset missing: $ds  — run: ./scripts/swe.sh fetch $SWE_REPO"; exit 2
    fi
    # Cloning + patching is the slow part; the generator skips fixtures it already built.
    "$PY" "$HERE/swe_fixtures.py" "$ds" --root "$SWE_ROOT" \
        --limit "$SWE_LIMIT" --reps "$SWE_REPS" "$@"
    ;;

  doctor)
    if [ $# -gt 0 ]; then "$PY" "$HERE/swe_doctor.py" --fixture "$1"
    elif [ -d "$SWE_ROOT" ]; then
      # Prove ONE fixture end-to-end (compile + the bug actually reproduces), then
      # compile-check the rest — a full test run per fixture would take hours.
      first="$(find "$SWE_ROOT" -maxdepth 1 -mindepth 1 -type d | sort | head -1)"
      [ -n "$first" ] && "$PY" "$HERE/swe_doctor.py" --fixture "$first"
      "$PY" "$HERE/swe_doctor.py" --all "$SWE_ROOT" --compile-only
    else "$PY" "$HERE/swe_doctor.py"; fi
    ;;

  run)
    [ -x "$SWE_ROOT/run_swe.sh" ] || { echo "no $SWE_ROOT/run_swe.sh — run build first"; exit 2; }
    [ -n "${DEEPSEEK_API_KEY:-}" ] || { echo "DEEPSEEK_API_KEY is unset"; exit 2; }
    # A generated script with ZERO fixtures is just a header: it exits 0 in silence,
    # which looks exactly like a hang. Count first and say so.
    n=$(find "$SWE_ROOT" -maxdepth 2 -name experiment.yaml | wc -l | tr -d ' ')
    if [ "$n" -eq 0 ]; then
      echo "no fixtures under $SWE_ROOT — nothing to run."
      echo "  build them first:  ./scripts/swe.sh build"
      echo "  (if build reported '0 fixture(s)', its output says why each instance was skipped)"
      exit 2
    fi
    echo "running $n fixture(s) from $SWE_ROOT — log: $SWE_ROOT/swe.log"
    echo "monitor from another terminal:  ./scripts/swe.sh status   (or: tail -f $SWE_ROOT/swe.log)"
    # Unbuffered: python block-buffers stdout into a pipe, so without this the tee'd
    # log arrives in silent 8KB bursts and an hours-long batch looks frozen.
    PYTHONUNBUFFERED=1 bash "$SWE_ROOT/run_swe.sh" 2>&1 | tee -a "$SWE_ROOT/swe.log"
    ;;

  status)
    "$PY" "$HERE/swe_status.py" "${1:-$SWE_ROOT}"
    ;;

  probe)
    # Memorisation probe: for each repo, fetch -> hidden-test fixtures -> compile
    # check -> run -> one cross-repo verdict table. Answers "can this repository
    # measure problem-solving, or does the model just recall the fix?".
    [ -n "${DEEPSEEK_API_KEY:-}" ] || { echo "DEEPSEEK_API_KEY is unset"; exit 2; }
    repos="${*:-${SWE_PROBE_REPOS:-fastjson2 logstash}}"
    lim="${SWE_LIMIT:-2}"
    echo "probe: [$repos] x $lim instance(s) x 1 rep, tests HIDDEN"
    for r in $repos; do
      root="${SWE_PROBE_BASE:-$ROOT}/swe-probe-$r"
      echo ""
      echo "───────── $r ─────────"
      "$PY" "$HERE/swe_fetch.py" --out "$MSB_DATA" "$r" || { echo "  skip $r: no dataset"; continue; }
      "$PY" "$HERE/swe_fixtures.py" "$MSB_DATA/$r.jsonl" --root "$root" \
          --limit "$lim" --reps 1 --hide-tests || { echo "  skip $r: build failed"; continue; }
      # Compile-only: on hidden-test fixtures the suite is green by design, so the
      # reproduce check is meaningless — and on big repos it costs tens of minutes.
      "$PY" "$HERE/swe_doctor.py" --all "$root" --compile-only || \
          echo "  ! $r: some fixtures do not build — they will be skipped below"
      [ -x "$root/run_swe.sh" ] || { echo "  skip $r: nothing to run"; continue; }
      PYTHONUNBUFFERED=1 bash "$root/run_swe.sh" 2>&1 | tee -a "$root/probe.log"
    done
    echo ""
    echo "───────── verdict ─────────"
    "$PY" "$HERE/swe_probe_summary.py" \
        --roots "${SWE_PROBE_BASE:-$ROOT}"/swe-probe-* --out "$ROOT/probe.md"
    ;;

  logs)
    # Collect only what FAILED, from every run's own log files — the console
    # scrollback is usually gone by the time anyone looks.
    "$PY" "$HERE/swe_logs.py" ${@:+--roots "$@"} --out "$ROOT/failures.md"
    ;;

  report)
    "$PY" "$HERE/d4j_ab_summary.py" "$SWE_ROOT" --runs-dir runs --out "$ROOT/swe-ab.md"
    ;;

  all)
    "$0" fetch && "$0" build && "$0" doctor && "$0" run && "$0" report
    ;;

  *)
    sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
    ;;
esac
