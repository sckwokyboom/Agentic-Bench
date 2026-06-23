# Phased Orchestration Harness — Design

**Date:** 2026-06-23
**Status:** Design approved (sections 1–5). Next: implementation plan.

## 1. Problem & hypothesis

The bench measures whether augmentations/tools help an LLM implement a stubbed
method (picocli `TextTable.putValue`). Observed across multiple traces:
`devstral2-24B` (self-hosted, `IDE-GPU-3`) fails `putValue` even WITH the impact
tool — but not on raw capability. It finds the right helpers
(`copy(BreakIterator,…)`, `getStyledChars`, `Column.overflow`), understands the
tool's BROAD signal, and calls `impact failures`. It fails on **discipline**:

- tunnel-visions on ONE test (`TextTableTest.addRowValues`), curve-fitting its
  literal expected output; never examines the other failing classes;
- oscillates (failure count bounces 302 ↔ 117 ↔ 123), and once deletes a brace →
  compile error;
- states a plan ("the change is broad, run the full suite") then ignores it and
  runs focused single-tests for 60 turns;
- declares done with 123 failures.

**Existence proof:** DeepSeek v4 Flash solves `putValue` *unaugmented*. So the
task is within a small model's reach; devstral2's gap is agentic discipline that
DSv4F has innately.

**Hypothesis:** forcing a fix methodology (understand → plan → implement →
diagnose, with gates) lets devstral2 succeed where its autonomous loop thrashes.

We have already established empirically that an *assist* layer (surfacing BROAD +
`impact failures`) is **necessary but insufficient** — the model had the info and
still thrashed. Hence the design principle: **force > assist**.

## 2. Goal & measurement

Orchestration is the **experimental variable**: A/B `orchestration: none` (bare
opencode = baseline) vs `orchestration: phased`, with augmentation held fixed.
The PLAN phase (section 4) is a further toggle, so conditions are
`{baseline, phased, phased+plan}`. Validation is by **objective metrics from UI
experiment runs on the server** (pass rate, cost, etc.) against the bare-opencode
baseline — there is no local interactive loop.

Non-goal for now: isolating each sub-mechanism (clustering vs gate vs phases);
those become later conditions.

## 3. Approach (B): an abench phase-controller driving opencode per phase

Chosen over:
- **A — constrained opencode** (strict prompt + hooks + forced tools): too soft;
  assist is already proven insufficient, and you cannot impose phase ORDER.
- **C — full LangGraph** replacing the opencode loop: biggest re-plumbing
  (bypasses opencode's trace pipeline, sandbox entrypoint, tool injection, model
  config) and the main risk to **metric comparability** with baseline — the very
  thing we are optimizing for. C remains a later evolution: the per-phase
  executor *inside* B can become a LangGraph node without changing the harness.

**Principle.** The controller owns control-flow + deterministic mechanics (phase
order, gates, test runs, clustering, regression-gate/revert, budget). The LLM
(opencode, per phase) owns content (contract, plan, code, fixes). Discipline is
enforced by code, not by prompt.

**Execution.** One workdir/container per rep; the controller makes N scoped
opencode `run_task` calls against it (code persists on disk between calls).
Between calls = deterministic Python.

## 4. Phase state machine

Four phases; **PLAN is a toggle** (`phased` vs `phased+plan`). Inter-phase state
is held by the controller and injected into the next phase's prompt; it is NOT
written into the workdir (keeps `git diff` / verify clean).

| Phase | Tools | Controller-supplied input | LLM output | Gate (controller) |
|---|---|---|---|---|
| **UNDERSTAND** | read, grep | target method (from `target_methods`); instruction to read its callers + a **diverse sample of tests across classes** | written **CONTRACT**: overflow modes (TRUNCATE/SPAN/WRAP), indent, line wrap, `Cell` return semantics, edge cases (null/empty/invalid-row) | structural: non-empty + mentions ≥2 of {TRUNCATE, SPAN, WRAP, indent, wrap, row}; else re-prompt ×1, then proceed |
| **PLAN** *(toggle)* | read | contract | **grounded approach sketch** naming the real helpers it will use (`copy(BreakIterator,…)`, `getStyledChars`, `Column.overflow`, "toString already pads columns") | non-empty; durable artifact, re-injected in DIAGNOSE |
| **IMPLEMENT** | read, edit | contract (+ plan) | method implementation | compiles (`:compileJava`); else bounded-repair ×M with the error |
| **DIAGNOSE-LOOP** | read, edit, `verify`-wrapper | contract (+ plan) + failure **CLUSTERS** (1 example/cluster, expected-vs-actual) | one fix targeting the **common root cause** | regression-gate: compiles AND failures not increased; else **auto-revert** + "made it worse N→M / broke compile, try another root cause" |

DIAGNOSE loop: controller runs the full suite → clusters failures → if green,
success; else present clusters → LLM fixes → re-run → gate (revert if worse) →
repeat. Show ALL clusters (breadth the agent never gets itself) but ask for ONE
root-cause fix (convergence) — this counters both tunnel-vision and whack-a-mole.

Controller-held state: `contract`, `plan` (if enabled), `best_snapshot`
(lowest-failure git state, for revert), `clusters` (recomputed each round).

Termination: green → success; budget (max_iters / tokens / wall-clock) →
stop@best; **K consecutive non-improving rounds** → stop@best (stuck). The final
verify gives the verdict — no leniency on "done".

Optional (not v1): re-plan-on-stuck instead of a plain stop.

The UNDERSTAND gate is **deterministic/structural** in v1 (no LLM judge — cheap,
no extra model dependency); an LLM-judge gate can be added later if needed.

## 5. Controller mechanics

- **Test execution (controller-owned).** Runs `:test --continue` and parses the
  **JUnit XML** reports (`build/test-results/test/TEST-*.xml`) into
  `(class, method, exceptionType, message, expected, actual)`. Reuse + extend
  abench's existing verify parser (it already yields pass/fail/names) to capture
  the failure message/diff. XML, not stdout scraping → robust.
- **Clustering.** Signature = `(exceptionType, normalized-diff fingerprint)`,
  where the fingerprint normalizes the `(expected, actual)` shape (collapse runs
  of spaces/digits) — so "wrong wrap position", "missing leading space", "extra
  row" bucket together, and `ComparisonFailure` vs `IndexOutOfBounds` are
  distinct buckets. One representative (shortest) per cluster; cap K (≤5); report
  "N failures in K clusters". Lives in a module **shared with the
  `impact failures` CLI** (DRY; one test suite).
- **Regression-gate + git auto-revert.** After IMPLEMENT, record
  `best = {git ref, failure_count}`. Each round: compiles AND failures ≤ best →
  **accept** (commit to a scratch ref; best := this); else
  `git checkout <best-ref> -- <files>` + feedback. Finalize at best (so
  `changes.patch` / verify see the best state, not a reverted mess). Git is
  defensive — fallback: restore file content from the snapshot; never crash the
  rep.
- **Observation curation.** In DIAGNOSE the model's tools are read, edit, and the
  `verify`-wrapper, which returns ONLY the curated cluster summary. Raw
  `--info` / `--continue` dumps never enter the model's context (prevents context
  bloat and tunnel). The model may still read source/tests, but cannot run raw
  gradle.
- **Budgets.** Per-phase turn/time cap (reuse opencode idle/loop/deadline
  watchdogs). DIAGNOSE: `max_iters` (≈8), K-no-progress (2–3), token + wall-clock
  ceilings. Overall rep ceiling.

## 6. Trace stitching, metrics, A/B cleanliness

- **Stitched Trace.** Concatenate each phase's steps (each tagged with optional
  `phase`) **plus synthetic `StepKind.CONTROLLER` steps** for deterministic
  events (ran-suite → "N failures in K clusters", accept/revert, phase
  transition). Concatenate turns → `tokens_in/out/cost` summed (LLM-only;
  controller test runs cost wall-clock, not tokens). `started/ended` span the
  whole rep. `final_diff_summary`, `target_similarity`, `verify_*` are computed
  post-hoc on the **final best state** — downstream unchanged.
- **Schema impact (additive only).** `Step.phase: str | None`; new
  `StepKind.CONTROLLER`; `Trace.orchestration_outcome: str | None`
  (green/budget/stuck/compile-fail). Baseline traces are untagged. Metrics
  pipeline + UI are unchanged (they read shared fields and ignore unknown kinds —
  `tool_calls` are counted only for `tool_call`). Safe-trace surfaces
  `phase`/`orchestration_outcome` (scrubbed, non-sensitive).
- **Comparability.** Headline metrics — `failed_count`, `tests_pass_rate`, verify
  verdict, `tokens_*`, `cost`, `duration`, `target_similarity`,
  `made_source_changes` — are computed identically → **directly comparable**
  baseline ↔ orchestrated. Shape metrics (`n_steps`, `n_tool_calls`) are inflated
  by controller steps but tagged → separable in analysis.
- **A/B validity.** baseline `none` (untouched opencode path) vs `phased`;
  everything else fixed (model, fixture, sandbox, verify, repetitions) → isolates
  orchestration. **No task leakage:** phase prompts reference the target method
  generically (from `target_methods`); the contract and plan are model-generated;
  the reference solution is never shown. The regression-gate + curation ARE the
  intervention (intended, not a confound); sub-mechanism isolation = later
  conditions.
- **Seam.** `stitch_traces(phase_results, controller_events) -> Trace`. The
  runner's orchestrated branch calls `orchestrator.run` → stitched Trace →
  downstream identical to baseline (write `trace.json`, verify, metrics). Only
  the SOURCE of the Trace differs.

## 7. Error handling

**Cardinal principle:** the orchestrator never crashes a rep — on any anomaly it
finalizes at `best` and runs the real verify; every abnormal path becomes a
recorded outcome, not a lost run. Reuse opencode `interrupted_reason` + watchdogs
per phase, and verify's passed/failed/error/skipped statuses.

- bad/empty contract → re-prompt ×1, then proceed with what we have;
- compile-fail after ×M repair → `outcome=compile-fail`, verify on best
  (likely all-fail), recorded honestly;
- opencode death/timeout/rate-limit mid-phase → finalize at best, record
  `interrupted_reason`;
- in-phase thrash → watchdog + per-phase budget; counts as a no-progress round;
- non-convergence → budget/stuck stop at best;
- gate/git edges: all-regress → K-no-progress; no-edit round → no-progress; git
  revert failure → file-content fallback → else abort loop + log (rep survives);
- test-infra error (cannot run tests, vs tests-failed) → treat as a phase error,
  finalize, record.

## 8. Testing

- **Unit (deterministic, no LLM/gradle).** `failure_report` (fixture XML →
  clusters/representatives; shared with the CLI); regression-gate decisions +
  no-progress counter + best-tracking; `git_snapshot` (temp repo
  snapshot/revert + defensive on bad state); phase state machine (mock phase
  results + gate outcomes → correct sequence, termination, finalize@best); trace
  stitching (fake phase Traces + events → one Trace with phase tags, summed
  tokens, CONTROLLER steps, span; round-trips `to_dict`/`from_dict`); budgets
  (stop at max_iters / K-no-progress). Injecting a fake `run_task` makes the
  whole orchestrator testable without a model — the key isolation boundary.
- **Integration (fake opencode).** A stub `run_task` returning canned
  edits/traces + a tiny stubbed-method fixture → `orchestrator.run` end-to-end →
  phases/gates/finalize/valid stitched trace, workdir at best. Tests the wiring
  without a real LLM or the full picocli build.
- **Real validation (user, on the server, via UI).** orchestrated vs baseline on
  objective metrics. CI covers the deterministic logic + wiring; "does it
  actually work" is decided by experiment metrics.

## 9. Units & integration seams

- **New:** `abench/orchestrator.py` (phase loop, gates, budget, prompt
  composition, git snapshot/revert); `failure_report` module (XML → clusters;
  shared with the `impact failures` CLI); `stitch_traces` (trace merge);
  `git_snapshot` helper.
- **Touched:** `config.py` (+`orchestration` condition knob); `runner.py` (branch
  to the orchestrator when enabled; baseline path untouched);
  `trace_model.py` (additive: `Step.phase`, `StepKind.CONTROLLER`,
  `Trace.orchestration_outcome`); `safe_trace.py` (surface phase/outcome).
- **Reused:** `opencode_client.run_task` (per-phase execution); the gradle
  invocation + verify parser; the impact clustering logic.

## 10. Complementary work & out of scope

- **Complementary (do now, orthogonal).** Enable vLLM prefix caching on the
  devstral endpoint (`--enable-prefix-caching`). Agent transcripts are
  append-only → a huge shared prefix each turn; caching cuts prefill GPU-time for
  ALL runs, is numerically safe, and is no A/B confound. Caching reduces the cost
  of *re-processing* the same prefix; orchestration reduces *how much* there is to
  process. Do both. (Whether the trace's `cache_read` populates depends on the
  endpoint reporting `cached_tokens` + opencode passing it through; the GPU-time
  win happens regardless.)
- **Later / out of scope.** LangGraph as the per-phase executor (evolution of B);
  sub-mechanism isolation conditions; LLM-judge contract gate; re-plan-on-stuck.
