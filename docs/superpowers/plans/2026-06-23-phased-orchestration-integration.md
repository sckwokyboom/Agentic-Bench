# Phased Orchestration — Plan 3: Runner/Config Integration (record)

**Date:** 2026-06-23. **Status:** wired + unit-tested (pure parts) on the Mac;
**real orchestrated run validated on the WSL box** (needs opencode + gradle +
container). Implemented directly (smaller, integration-heavy) rather than as a
separate TDD plan.

Spec: `2026-06-23-phased-orchestration-design.md`. Builds on Plan 1 (foundation)
+ Plan 2 (orchestrator core), both merged.

## What was wired

- **`abench/orchestration_adapters.py`** (new):
  - `eval_from_junit(dir, compiled, ran) -> SuiteEval` — JUnit XML → full
    breakdown (executed/passed/failed/errors/skipped) + per-test failures. *(unit-tested)*
  - `make_suite_runner(workdir, command, timeout)` — clears stale results, runs
    the test command as a **host subprocess** (same approach as `verify.py`), then
    `eval_from_junit`. compiled inferred from compile-error markers. *(thin; WSL-validated)*
  - `extract_phase_text(trace)` — the agent's final assistant message = the
    contract/plan. *(unit-tested)*
  - `make_phase_runner(client, …)` — one `run_task` per phase on the same
    workdir, tools scoped to the phase. *(wiring unit-tested with a fake client)*
  - `build_orchestrator_config(orch_cfg, mode)` — OrchestratorConfig from the
    experiment block + mode. *(unit-tested)*
- **`abench/config.py`**: `Condition.orchestration: str|None` (`phased`/`phased_plan`);
  experiment-level `OrchestrationCfg` (`contract_fields`, `target_label`,
  `max_diagnose_iters`, `no_progress_limit`, `cluster_cap`). *(unit-tested)*
- **`abench/runner.py`**: per-rep branch — when `cond.orchestration` is set,
  build adapters + call `orchestrator.run` → one stitched `Trace` wrapped in
  `RunResult`; else the existing single `run_task`. Downstream (diff, trace.json,
  verify, metrics) unchanged. Baseline path byte-identical.

## How to run on WSL (compare against baseline)

1. `git pull` on main, rebuild the sandbox image, ensure `--enable-prefix-caching`.
2. In the experiment YAML add the `orchestration` block + conditions, e.g.:
   ```yaml
   orchestration:
     contract_fields: [TRUNCATE, SPAN, WRAP, indent, wrap, row]
     target_label: "TextTable.putValue"
   conditions:
     - {name: impact-only, augmentation: ./slices/impact-tool-briefing.md,
        overlay: ./overlays/impact-artifacts, tools: [impact]}          # CONTROL
     - {name: phased,      augmentation: ./slices/impact-tool-briefing.md,
        overlay: ./overlays/impact-artifacts, tools: [impact], orchestration: phased}
     - {name: phased_plan, augmentation: ./slices/impact-tool-briefing.md,
        overlay: ./overlays/impact-artifacts, tools: [impact], orchestration: phased_plan}
   ```
3. Run via UI; compare `impact-only` vs `phased(+plan)` on `tests_pass_rate`
   (primary), then the cost split. Interleave condition order (isolation.shuffle_order).

## Open tunables (resolve on the box if needed)

- **Per-phase `run_task`**: currently a fresh opencode session per phase (state
  carried by the workdir); no per-phase `log_sink`/`debug_sink`/`cancel_event`
  threaded yet (live UI log shows events via `on_event` only). Thread them if the
  UI/cancel UX matters.
- **`agent_tools` scoping**: `{tool: True for tool in allowed_tools}` per phase —
  confirm opencode disables the unlisted tools as the baseline condition does.
- **Per-phase timeout**: uses `exp.timeout_s` (whole-run) per phase; the diagnose
  loop is bounded by `max_diagnose_iters`/`no_progress_limit`. Add a per-phase
  cap if a phase can hang.
- **Rate-limit retries**: the orchestrated branch runs once (no per-phase 429
  retry loop). A rate-limited phase surfaces via its trace; revisit if 429s are
  frequent.
- **`suite_runner` flaky re-confirm**: re-runs the whole suite; optimize to re-run
  only the newly-failing tests for speed if suite runtime dominates.
- **compiled heuristic**: marker-based (`COMPILATION ERROR`/`cannot find symbol`/
  `error: `/`BUILD FAILED`); tighten against real gradle output on the box.
