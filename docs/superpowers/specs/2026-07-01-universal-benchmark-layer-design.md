# Universal Benchmark Layer — Design

**Date:** 2026-07-01
**Status:** Approved design (pre-implementation-plan)
**First target:** SWE-bench-java-verified (91 instances). **Second target (future):** Java-Bench (OO code-gen shape).
**Pilot slice:** `fasterxml/jackson-core` (23 instances, 1 official image).

---

## 1. Motivation & goals

Extend the `abench` A/B agentic-coding harness to run **standard, isolated, reproducible, academically-comparable** software-engineering benchmarks — starting with SWE-bench-java — **without rebuilding the harness** and **without burning machine resources** to keep them runnable.

The current task model (`fixture_path`/`reference_path`, a single stripped target method, whole-suite verify) is picocli-specific. SWE-bench-java tasks are different: 91 GitHub-issue-resolving instances across 6 repos (79% Jackson), gold patches are multi-file (67%, median +18 LOC), the oracle is 1–3 **test classes** (`module:pkg.ClassFQN`) in `FAIL_TO_PASS`, and `PASS_TO_PASS` is **empty for all 91** (the official criterion has no regression guard).

We want a **universal seam**, not a bespoke adapter: the same runner, metrics, traces, and A/B conditions must serve both issue-resolving (SWE-style) and code-generation-to-tests (Java-Bench-style) benchmarks.

## 2. Hard invariants (non-negotiable)

These bound every design decision below.

1. **No gold leakage.** The gold patch and anything derived from it (expected FAIL_TO_PASS/PASS_TO_PASS resolution, reference solution) are NEVER visible to the agent or to any agent-facing augmentation. Enforced structurally (§4), not by discipline.
2. **No test leakage.** The hidden evaluation tests (`test_patch` / FAIL_TO_PASS) are NEVER shown to the agent, in any form, not even a labelled "special" run. A reader who sees "SWE" must be seeing an honest standard run — a disclosed-but-non-standard run is still academic deception. Any augmentation that would require exposing evaluation tests is out of scope. If such an ablation is ever needed, it must run **under a different benchmark name** so it can never be read as SWE.
3. **Maximal fidelity to the original protocol.** Agent input = `problem_statement` + `repo@base_commit`, identical to canonical SWE-bench. `hints_text` OFF by default (PR discussion may spoil the fix). The authoritative verdict comes from the **official evaluator**, run offline against a **pinned** version.
4. **Honesty guardrail in results.** Every result carries `standard_protocol: true|false` + the evaluator pin. Export/report under the name "SWE-bench-java" is permitted **only** for `standard_protocol: true` results.

## 3. Approach (chosen: A — adapter seam inside abench)

A `BenchmarkAdapter` seam inside abench emits benchmark instances into the **existing** run pipeline (`create_workdir → run_opencode → grade → metrics/trace`). Rejected alternatives: (B) pre-generating 91 standalone experiment dirs — clutters disk, materializes 91 repos, poor fit for code-gen, awkward dual-grading; (C) inverting control under the official harness — loses the A/B condition system, phased orchestration, and trace stitching, and doesn't generalize to a second benchmark.

## 4. Component: BenchmarkAdapter protocol + leakage firewall

New module `abench/bench/`. A benchmark is a source of *instances*; each instance flows through the existing pipeline.

```python
class BenchmarkAdapter(Protocol):
    id: str                                    # "swebench-java", "javabench"
    def load(ref, subset) -> Iterable[Instance]
    def env(inst)        -> EnvSpec            # official image ref + module_map + build_system
    def materialize(view: AgentView, workdir)  # lay down the agent-visible working state
    def task(view: AgentView)    -> TaskSpec    # only legitimate agent input (issue text / codegen spec)
    def anchors(view: AgentView) -> Anchors     # legitimately-known anchor(s) for augmentation
    def grade(inst, source_diff, ctx) -> GradeResult   # {official, abench}
```

**Two disjoint data planes (structural firewall — invariants 1 & 2):**

- `AgentView` — everything the agent *may* see and everything augmentation is built from: task spec, materialized env, `anchors`. All derivable **without** gold patch and **without** hidden tests. `AgentView` literally does not contain `patch`, `test_patch`, or `FAIL_TO_PASS`/`PASS_TO_PASS` fields.
- `OracleView` / full `Instance` — gold patch, hidden `test_patch`, expected resolution. Reachable **only** by `grade()`.

`materialize / task / anchors` receive `AgentView`; so does the shared **tipper** component (§6), which is triggered by a condition's `augmentation: auto` (not an adapter method — the tipper is Java-graph-based and shared across adapters). `grade()` is the only function that sees the full `Instance`. To leak gold or tests one would have to deliberately change signatures — the type boundary is the guarantee.

**Illustrative shapes** (finalized in the plan):

```python
EnvSpec:  {image: str, workdir_mount: str, module_map: dict, build_system: "maven"|"gradle"}
TaskSpec: {prompt_text: str, allowed_context: list[str] | None}
Anchors:  {existing_tests: list[str], issue_entrypoints: list[str]}   # static seeds only; NEVER the hidden FAIL_TO_PASS.
          # The agent-repro corridor (§6) is captured at RUN time by the tipper, not here.
GradeResult:
  official: {resolved: bool | None, evaluator: "multi-swe-bench@<pin>", raw_report: dict}
  abench:   {regressions_introduced: list[str], repro_reproduced: bool, ...agent_run_metrics}
  standard_protocol: bool
```

**Config seam** (alternative to `fixture_path`/`reference_path`):

```yaml
benchmark:
  adapter: swebench-java
  dataset: ./data/swe-bench-java-verified.json
  subset: {repo: fasterxml/jackson-core}      # pilot filter
conditions:                                    # reused unchanged
  - {name: baseline,        augmentation: null}
  - {name: tipper-anchored, augmentation: auto}
```

When `benchmark:` is present, the runner iterates `instances × conditions × repetitions`; per-instance fixture/env come from the adapter.

**Module layout** (small, single-purpose files): `bench/base.py` (protocol + dataclasses + `AgentView`/`OracleView`), `bench/registry.py` (id → adapter), `bench/swebench_java.py` (first adapter), `bench/tipper.py` (shared test-anchored tipper, §6), `bench/grading/base.py` + `bench/grading/official.py` (§7), thin "expand instances" branch in `runner.py`.

## 5. Component: isolation & egress-lock

**Two container roles per instance, both from the official image (nothing rebuilt):**

1. **Agent-run container** — from `env(inst).image`; the agent edits a working copy. Egress-locked.
2. **Grading container** — a *clean* instance of the same image; the official evaluator applies the agent's `source_diff` + its own `test_patch` to a pristine checkout and runs FAIL_TO_PASS/PASS_TO_PASS. The verdict comes from here, never from the agent's dirty workdir. Fully **offline** (deterministic).

**Egress-lock (invariants 2 & 3 — structural network boundary):**

- The agent-run container runs on an **internal docker network with no external gateway**, beside a **proxy sidecar with an allowlist** that permits `CONNECT` only to the model host(s). GitHub / Maven Central / arbitrary web are physically unreachable — no route, not merely "discouraged".
- The **build runs offline** because dependencies are baked into the official image (that is the point of these images). If a repo needs an uncached transitive dep, we derive one thin layer on top of the official image **once**, not per run.
- The allowlist is **auto-derived** from the experiment's `providers[].base_url` → no manual drift. For a local vLLM model, the sidecar bridges to the host.
- `cheating.py` remains a second layer (git-network attempts, gold-similarity at grade time).

This structurally eliminates the "look up the upstream fix" leakage class — what makes `official.resolved` honestly comparable.

**Resources (constraint: don't burn the machine):** reuse official images (pull once, ~6 for the whole bench; pilot jackson-core = 1); lazy-pull only the subset being run; ephemeral containers torn down after each run; **repos are never materialized to disk as 91 trees** — the repo lives inside its image, only the agent's overlay/diff is on disk. Helper `bench images pull|prune`; optional CPU/mem limits in `SandboxCfg`.

**Config:** `SandboxCfg` gains `egress: open|allowlist` (+ auto `allowlist_hosts`); image resolved by the adapter's `env()`.

## 6. Component: test-anchored tipper (agent-repro, issue-only) — the research core

**Anchoring setting: agent-repro, issue-only — the only tipper arm.** This sits **inside** the standard SWE-bench setting, so it is honest and leaderboard-comparable:

- Agent input is exactly `problem_statement` + `repo@base_commit` (canonical).
- The agent writes **its own** reproduction test from the issue (as SWE-agent / Agentless / real developers do). The hidden `test_patch` is absent from disk and blocked by the `AgentView` firewall.
- The tipper probes the agent's **own** repro — a scaffold tool over agent-visible artifacts, analogous to retrieval/execution tools other systems use. The leaderboard compares (model + scaffold) systems under identical inputs; a better scaffold is a contribution, not deception. The scientific claim is the **`tipper − baseline` delta**.

**Tipper artifact** (same markdown family as the existing `*-graph-slice.md`, but unrolled BACKWARD from the anchor):

```
# Test-anchored slice / <instance_id>
## Anchor                        # the agent's own repro test
## Reachability BACKWARD         # from the anchor into production code:
   candidate sites: signature + body-slice + siblings + callers   # statically reachable neighbourhood
## Runtime corridor (invasive)   # println / Byte Buddy on the anchor run:
   actual args/return/throw along the corridor; where it diverges
## NB: fix location NOT asserted — candidates only
```

**Invariant:** the slice surfaces a **blast-radius of candidates**, never "the method to fix" (that would come from gold). The agent still performs localization.

**Reuse of existing components:** `runtime_chain.py` (corridor from `.runtime-capture.jsonl`), `runtime_evidence.py` (diagnostic card), `reachability.py` / `graph_cover.py` / `methods.py` + Joern (backward reachability & method extraction), and the `forced-instrument-in-test.md` methodology (agent writes/instruments the repro). The tipper anchors on the agent's repro instead of a known target method.

**Dropped:** the with-tests arm — removed entirely from scope per invariant 2.

## 7. Component: dual-grading (official verdict + abench statistics)

**Split the agent's diff.** After the agent finishes, `diff_workdir()` yields the full diff:
- **source-diff** (non-test files) → the graded "prediction".
- **test-diff** (test files = the agent's repro) → kept for abench analysis/trace only; **never** sent to grading. Matches SWE convention (models patch non-test code; eval tests come from the harness) and removes any grade-gaming vector.

**Official verdict (delegated).** In the clean grading container: the official multi-swe-bench evaluator applies its `test_patch`, runs FAIL_TO_PASS/PASS_TO_PASS → `resolved: bool`. Pinned evaluator (digest/commit in provenance), offline. This is the headline number, from the source of truth — not a reimplementation.

**abench statistics (same run, alongside).** The official criterion has **no regression guard** (empty PASS_TO_PASS) — exactly what abench adds:
- Regressions: tests green on `base + source-fix` but red after the agent's diff. **Scoped to the modules / blast-radius of the touched methods** (reuse the graph: method → covering tests) rather than the whole suite — cheaper and resource-light; full-suite is an optional flag.
- `repro_reproduced`: did the agent's repro actually fail on base (quality of its own anchor).
- Plus the agent-run metrics: tokens, tool-calls, steps, time-to-first-edit, diff size, cheating signals.

**Universal grading seam.** `bench/grading/base.py`: `Grader.grade(inst, source_diff) -> GradeResult{official, abench}`. SWE-java → wraps the official evaluator. Java-Bench (future) → "official" = running its provided suite (that *is* its academic criterion); abench stats via the same instrumentation. One result shape, two benchmark forms.

## 8. Component: metrics & traces

Mostly reuse. `metrics.py` unchanged for tokens / tool-calls / steps / timings / diff-stats / cheating. Added `metrics.json` fields: `instance_id`, `repo`, `official.resolved`, `abench.regressions_introduced`, `repro_reproduced`, `standard_protocol`, `evaluator_pin`. Traces: `trace_stitch` / `safe_trace` unchanged; repro and tipper-probe events flow through opencode events; the runtime-corridor card (`runtime_evidence`) attaches to the trace as `phased_runtime` does today. `report.py` / `render_results` extended: per-instance → per-repo → overall aggregation; **headline = official resolved-rate + `tipper − baseline` delta with CIs, stratified by repo** (Jackson dominance ⇒ report per-repo, not just pooled); abench regression-rate as a secondary, clearly-labelled column. Trace analysis uses the same tooling, now across benchmark instances.

## 9. Pilot scope

- Dataset: `swe-bench-java-verified.json` (downloaded), subset `fasterxml/jackson-core` (23 instances, 1 official image).
- Arms: `baseline` (issue-only) vs `tipper-anchored` (agent-repro, issue-only).
- Metric: official resolved-rate (both arms) + delta; abench regression-rate secondary.
- Success of the pilot: the harness runs end-to-end on jackson-core with `standard_protocol: true`, produces an official verdict matching the official harness on a spot-check, and yields interpretable baseline-vs-tipper numbers. If the delta signal is real → extend to the other 5 repos.

## 10. Risks & open questions (for the plan)

- **Official evaluator integration mechanics** — invoke the pinned multi-swe-bench harness/CLI vs. driving its Docker image directly; exact predictions-file format; how it reconciles agent test edits (we pre-strip test-diff, so low risk).
- **Image availability/size** — confirm official jackson images exist and run offline; size budget for pull/prune.
- **Agent-repro variance** — a weak repro yields weak augmentation (acceptable, no leakage); measure `repro_reproduced` to quantify.
- **Joern cost on large repos** — jackson-databind is large; cache CPG per (repo, base_commit).
- **Statistical power** — N=91, Jackson-dominant ⇒ wide CIs; per-repo stratified reporting is required, pooled numbers alone are misleading.
- **Second axis of build systems** — 5 Maven + 1 Gradle (jib); verify auto-detect already covers both, but class-level selection differs (`mvn -pl <module> -Dtest=<Class>` vs gradle `:<module>:test --tests <FQN>`).

## 11. Non-goals

- No oracle-localized tipper (targets from gold patch) — deleted from consideration.
- No with-tests / test-exposing arm under the SWE name.
- No rebuild of the condition / orchestration / trace systems.
- No full-suite grading by default (scoped regression only), to stay resource-light.
