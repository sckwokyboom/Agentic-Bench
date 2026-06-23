# Phased Orchestration Harness — Design

**Date:** 2026-06-23
**Status:** Design v2 (incorporates external review). Scoped as a **case study**
on one failure mode (picocli `TextTable.putValue`). Next: implementation plan.

> v2 changes vs v1: explicit condition matrix (control = `impact-only`, not bare
> opencode); generic-orchestrator / task-fixture separation; softened causal
> claim; multi-factor + flaky-robust regression-gate; full-worktree snapshot;
> edit allowlist; structured/sanitized contract & plan; evaluation protocol;
> controller-overhead metrics; clustering corpus + prioritization.

## 1. Problem & hypothesis

The bench measures whether interventions help an LLM implement a stubbed method
(`TextTable.putValue`). Across traces, `devstral2-24B` (self-hosted `IDE-GPU-3`)
fails `putValue` even with the impact tool — but not on raw capability: it finds
the right helpers, understands the tool's BROAD signal, calls `impact failures`.
It fails on **discipline**: tunnel-visions on one test, oscillates (failure count
302 ↔ 117 ↔ 123), once deletes a brace (compile error), states a plan then
ignores it, declares done with 123 failures.

DeepSeek v4 Flash solves `putValue` *unaugmented*. **This shows the task is
tractable for a small coding agent — it does NOT prove devstral's failure is
purely discipline** (DSv4F may also have better Java priors, reasoning, or
tool-use). We therefore *hypothesize* that devstral's failures are substantially
methodology-driven (the thrash patterns are the evidence), and this experiment
**tests** that hypothesis. We already established that an *assist* layer
(surfacing BROAD + `impact failures`) is necessary but **insufficient** — the
model had the info and still thrashed. Design principle: **force > assist**.

**Scope: this is a case study on one known failure mode**, not a general claim
about agentic discipline. Generalization (other tasks/repos) is explicitly later
work (§10).

## 2. Goal, condition matrix & evaluation

Orchestration is the **experimental variable**. To attribute a win to the
*forced structure* (and not to a different tool or feedback form), the control is
**`impact-only`, not bare opencode**.

| Condition | What it is |
|---|---|
| `impact-only` (**control**) | autonomous opencode + the impact tool (incl. `impact failures` clustering available). = the existing `augmented-tool` condition. |
| `phased` | orchestration (UNDERSTAND → IMPLEMENT → DIAGNOSE); controller forces curated clusters into the loop and blocks raw test dumps. |
| `phased+plan` | `phased` + the PLAN phase. |

**Contrasts:** `impact-only → phased` isolates the **forced structure + curation
discipline** (both conditions have the *same clustering capability available*;
`phased` forces it + blocks raw dumps — so the delta is the forcing/structure,
**not** the availability of clustering). `phased → phased+plan` isolates the
**PLAN** phase. Deferred (§10): `bare` opencode and the full factorial.

**Evaluation protocol (so metrics aren't anecdotal):**
- N repetitions per condition (N pinned in the plan; ≥ enough for a distribution).
- Fixed, **reported** temperature/sampling; same model/config/sandbox across
  conditions.
- **Primary endpoint:** `tests_pass_rate` (= passed / `expected_total`).
  Secondary: `failed_count`, cost split (§6), wall-clock.
- Report the **distribution / CI** across reps, not a single number; define what
  counts as a meaningful improvement before running.
- **Flaky handling:** see §5 (gate re-confirms regressions); flaky-flagged tests
  reported separately.
- **Randomize / interleave** condition order across reps + warmup, so prefix-cache
  warmth (§10) doesn't bias duration toward whichever runs second.

## 3. Approach (B): an abench phase-controller driving opencode per phase

Chosen over A (constrained opencode — too soft; assist proven insufficient) and C
(full LangGraph — biggest re-plumbing, bypasses opencode's trace pipeline →
threatens metric comparability). C remains a later evolution: the per-phase
executor *inside* B can become a LangGraph node without changing the harness.

**Principle.** The controller owns control-flow + deterministic mechanics; the LLM
(opencode, per phase) owns content. Discipline is enforced by code, not prompt.

**Generic orchestrator vs task fixture — a hard boundary.** The orchestrator is
**task-agnostic**. All task-specific scaffolding — which callers/tests to read,
the contract's required fields, any helper hints for PLAN, the target source root
— comes from **fixture/experiment config** (extending `target_methods`), never
hardcoded in `orchestrator.py`. Every picocli/`putValue`-specific token in this
doc (`TRUNCATE/SPAN/WRAP`, `copy(BreakIterator,…)`, `getStyledChars`) is an
**illustrative example of what the fixture config supplies**, not orchestrator
logic. This keeps the case-study honest and the orchestrator reusable later.

**Execution.** One workdir/container per rep; the controller makes N scoped
opencode `run_task` calls against it (code persists between calls). Between calls
= deterministic Python.

## 4. Phase state machine

Four phases; **PLAN is a toggle** (`phased` vs `phased+plan`). Inter-phase state
is held by the controller and injected into the next phase's prompt as a
**structured, length-capped, sanitized** artifact; never written into the workdir
(keeps `git diff` / verify clean) and never trusted verbatim (it is model output —
schema-validated + sanitized before re-injection, to prevent self-poisoning /
injected instructions).

| Phase | Tools | Controller-supplied input | LLM output | Gate (controller) |
|---|---|---|---|---|
| **UNDERSTAND** | read, grep | target method; **config-listed** callers + a deterministic diverse test sample (§5) | **CONTRACT** as structured fields (config defines the field set: behaviors, edge cases, return semantics) | (a) structured: required fields present + non-trivial; (b) behavioral: the phase actually read the configured callers + ≥ N test classes. Else re-prompt ×1, then deterministic fallback (below) |
| **PLAN** *(toggle)* | read | contract | structured approach sketch referencing concrete methods/tests it read | structural + behavioral: references ≥1 real symbol from files it read (generic — not a keyword match on task terms) |
| **IMPLEMENT** | read, edit *(allowlisted, §5)* | contract (+ plan) | implementation | compiles (`:compileJava`); else bounded-repair ×M with the error |
| **DIAGNOSE-LOOP** | read, edit *(allowlisted)*, `verify`-wrapper | contract (+ plan) + prioritized failure CLUSTERS (1 example/cluster, expected-vs-actual) | one fix targeting the common root cause | multi-factor regression-gate (§5); else auto-revert + feedback |

- DIAGNOSE loop: controller runs the suite → clusters → green ⇒ success; else
  present clusters → LLM fixes → re-run → gate (revert if worse) → repeat.
- Show ALL clusters (breadth) but ask for ONE root-cause fix (convergence) —
  counters tunnel-vision + whack-a-mole.
- **UNDERSTAND fallback** (force > assist, but no hard wedge of a weak model): if
  the gate still fails after one re-prompt, the controller **synthesizes a minimal
  contract** from the read tests/clusters and proceeds — methodology is preserved
  deterministically rather than "proceeding with garbage" or wedging the rep.
- Termination: green → success; budget (max_iters / tokens / wall-clock) →
  stop@best; **K consecutive non-improving rounds** → stop@best (stuck). Final
  verify gives the verdict — no leniency on "done".
- Gates are **deterministic/structural+behavioral** in v1 (no LLM judge). Optional
  later: re-plan-on-stuck.

## 5. Controller mechanics

**Edit allowlist (validity / anti-cheat).** Edits are restricted to the configured
target source root (e.g. the target file). Any edit touching `src/test/**`,
`build.gradle*`, CI/config, or generated reports is **rejected/reverted** and fed
back as a violation. (Closes a cheating vector; aligns with the existing
cheating-detector.)

**Test execution (controller-owned).** Runs `:test --continue`, parses **JUnit
XML** (`build/test-results/test/TEST-*.xml`) → per-test
`(class, method, status, exceptionType, message, expected, actual)`. Reuse +
extend abench's verify parser. Capture **execution status** (ran / error /
skipped) and **executed-test count**, not just failed count.

**Multi-factor regression-gate.** Accept the round only if **all**: compiles; the
suite actually executed (not an infra error); executed-test count not decreased;
and (passed_count increased) OR (failed_count decreased AND no new errors/skips).
`failed_count` alone is insufficient (a drop can hide stopped/skipped tests or a
worse scenario breaking). On reject → revert + "made it worse (passed N→M /
broke compile / fewer tests ran), try another root cause."
**Flaky robustness:** before treating a round as a regression, **re-run the newly
failing tests once**; only a confirmed regression triggers revert (a flaky flip
must not corrupt the gate). Flaky-flagged tests are logged.

**Snapshot / revert (robust).** Full-worktree snapshots, not file-level checkout:
a temporary commit (or stash) of the whole worktree; revert =
`git reset --hard <snap> && git clean -fd` (restores tracked, removes untracked),
with forbidden-path edits rejected up front. Handles untracked/deleted/renamed/
chmod that `git checkout -- <files>` misses. Defensive: never crash the rep.
**Initial `best`** = the **stub state** + its failure_count from an initial
controller verify (before any edit). Compile-fail keeps `best` at the stub.

**Clustering.** Needs a **fixture corpus of real `TEST-*.xml`** + explicit
extraction rules & fallbacks (expected/actual sometimes only in the message;
non-`ComparisonFailure` exceptions; parameterized/unstable names; setup/teardown
failures). Signature = `(exceptionType, normalized-diff fingerprint)`. **Selection
is prioritized, not top-K-by-size:** compile/test-infra first → exceptions (e.g.
`IndexOutOfBounds`, often the root) → target-related tests → then largest, but
**always surface rare-but-severe** clusters. Cap the shown count but order by
priority. Shared module with the `impact failures` CLI.

**Diverse test sample (UNDERSTAND).** **Deterministic and logged** — derived from
the impact coverage/callers data, stratified across classes (not hand-picked, or
it's leakage).

**Observation curation.** DIAGNOSE tools = read, edit (allowlisted), `verify`-
wrapper returning ONLY the curated cluster summary. Raw `--info`/`--continue`
dumps never enter the model's context.

**Budgets.** Per-phase turn/time cap (reuse opencode idle/loop/deadline
watchdogs). DIAGNOSE: `max_iters` (≈8), K-no-progress (2–3), token + wall-clock
ceilings. Overall rep ceiling. **Log diff breadth** per round (touched
files/methods, ± lines) — a soft signal for "one root-cause fix vs rewrote half
the class".

## 6. Trace stitching, metrics, A/B cleanliness

- **Stitched Trace.** Concatenate phase steps (each tagged optional `phase`) +
  synthetic `StepKind.CONTROLLER` steps for deterministic events. Concatenate
  turns → tokens/cost summed (LLM-only). `started/ended` span the rep.
  `final_diff_summary`, `target_similarity`, `verify_*` computed post-hoc on the
  **final best state** — downstream unchanged.
- **Schema impact (additive only).** `Step.phase: str|None`; new
  `StepKind.CONTROLLER`; `Trace.orchestration_outcome` (green/budget/stuck/
  compile-fail); plus controller-overhead fields below. Baseline traces untagged;
  metrics pipeline + UI unchanged (ignore unknown kinds).
- **Honest cost accounting (don't let orchestration look "cheaper").** Break out:
  `llm_tokens`/`llm_cost`, `controller_test_time`, `num_full_suite_runs`,
  `num_verify_calls`, `accepted_rounds`/`reverted_rounds`, `num_curated_reports`,
  `wall_clock_total`. (Reuses the `llm_latency_s`/`tool_exec_s` placeholders in
  `trace_model`.) Tokens are LLM-only; the controller's repeated full-suite runs
  cost wall-clock, so report both — orchestration may be cheaper in tokens but
  costlier in server time.
- **Comparability.** `impact-only` and `phased` produce the same trace/metric
  schema → headline metrics (`tests_pass_rate`, `failed_count`, cost split,
  duration, `target_similarity`, `made_source_changes`) directly comparable.
  Shape metrics inflated by CONTROLLER steps but tagged → separable.
- **Leakage, stated precisely.** No **reference-solution** leakage (the original
  is never shown). **Task-specific scaffolding IS present** (config-supplied
  callers/fields/hints) and is **declared as part of the intervention/fixture**;
  it lives in config, not the orchestrator. Conclusions are scoped to this case
  study.

## 7. Error handling

Cardinal principle: the orchestrator never crashes a rep — on any anomaly it
finalizes at `best` and runs the real verify; every abnormal path → a recorded
outcome. Reuse opencode `interrupted_reason` + watchdogs; verify statuses.
Cases: bad/empty contract → re-prompt ×1 → deterministic minimal-contract
fallback (§4); compile-fail after ×M → `outcome=compile-fail`, verify on best
(stub); opencode death/timeout/rate-limit mid-phase → finalize at best, record
reason; in-phase thrash → watchdog + per-phase budget; non-convergence →
budget/stuck@best; gate/git edges → confirmed-regression-only revert,
file-fallback then abort-loop+log; test-infra error (can't run vs tests-failed) →
phase error, finalize, record.

## 8. Repo invariants (post-rep)

Explicit, enforced: final workdir is clean **except allowed source edits**; **no
test/build/config edits** (allowlist); compile succeeds OR outcome =
`compile-fail`; **final verify always runs from scratch**; `changes.patch` is
generated from the **best** state; all controller prompts, the contract, the plan,
and controller events are saved as **run artifacts**.

## 9. Testing

- **Unit (deterministic, no LLM/gradle).** `failure_report` over a **fixture XML
  corpus** (ComparisonFailure, IndexOOB, message-only, parameterized, setup
  failure) → extraction + clustering + prioritization; multi-factor gate decisions
  (incl. fewer-executed / new-skips / flaky re-confirm) ; `git_snapshot`
  robustness (untracked/deleted/rename, forbidden-path reject); phase machine
  (mock results → sequence/termination/finalize@best, incl. contract fallback);
  trace stitching (fake phase Traces+events → one Trace, tags, summed tokens,
  CONTROLLER steps, overhead fields; round-trip); budgets. Inject a fake
  `run_task` → whole orchestrator testable without a model.
- **Integration (fake opencode).** Stub `run_task` + tiny stubbed-method fixture →
  `orchestrator.run` end-to-end → phases/gates/finalize/valid stitched trace,
  allowlist enforced.
- **Real validation (user, on server, via UI).** `impact-only` vs `phased(+plan)`
  on the protocol in §2.

## 10. Units, seams, scope

**New:** `abench/orchestrator.py` (phase loop, gates, budget, prompts, snapshot/
revert, allowlist); `failure_report` (XML → prioritized clusters; shared with
`impact failures` CLI); `stitch_traces`; `git_snapshot` helper.
**Touched:** `config.py` (+`orchestration` knob + task-fixture scaffolding fields);
`runner.py` (branch to orchestrator; baseline path untouched); `trace_model.py`
(additive fields above); `safe_trace.py` (surface phase/outcome/overhead).
**Reused:** `opencode_client.run_task`; gradle invocation + verify parser; impact
clustering.

**Complementary (now, orthogonal):** enable vLLM prefix caching
(`--enable-prefix-caching`) — cuts prefill GPU-time for all runs; numerically
safe; not a correctness confound, but **a duration confound if run order is fixed**
→ handled by interleaving + warmup + logging hit-rate (§2).

**Deferred / out of scope:** `bare` condition + full factorial; multi-task
generalization (this is a case study); LangGraph per-phase executor; re-plan-on-
stuck; LLM-judge gates; a broader **safe-trace scrub policy** for non-OSS targets
(picocli is OSS; the existing scrubber covers v1).

**v1 sequencing (for the plan):** core `UNDERSTAND → IMPLEMENT → DIAGNOSE` with
simple-but-prioritized clustering, full-worktree snapshot, multi-factor gate,
minimal stitched trace + overhead metrics, allowlist. **PLAN** is the next
increment (it's the toggle we measure). Shared-CLI refactor, re-plan, safe-trace
polish: later.

## Open implementation questions (for writing-plans)

- `run_task` per phase: new session vs continued; workdir/tool-permission
  enforcement; how phase traces are extracted; timeout/death/abort representation;
  retry/provider-error handling.
- Container/daemon/cache determinism across the controller's repeated suite runs
  (gradle daemon off? generated-file hygiene? network).
- N, temperature, and the "meaningful improvement" threshold for §2.
