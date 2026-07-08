# RapidCausalCoder Lite (wow-MVP) — design

**Date:** 2026-07-08
**Status:** approved (brainstorming) → next: implementation plan (phase 1)

## Motivation

RapidCausalCoder is the lightweight, prompt-driven version of the CausalCoder++
concept: after a lead LLM produces a code diff, a reactive LangGraph tool builds
a mutational subgraph around the change, writes textual specs per method
(prompt **Alpha**), collects dynamic evidence via invasive println debugging
(prompt **Beta** + instrumenter), turns (subgraph + specs + logs) into a causal
graph — the CausalDeltaSubGraph (prompt **Gamma**), ranks root causes
(CausalRank = Σ outgoing causal-edge weights), generates a targeted fix,
verifies subset → full suite, and caches successful insights in a **Memory
Graph**. The MVP proves three claims on the bench, honestly: (1) the causal
graph points at the root better than a plain call graph, (2) the Memory Graph
skips re-analysis on repeat encounters, (3) dynamic logs are the ingredient
that turns correlation into causation.

**Key economics:** most of the machinery already exists in this bench —
method→tests coverage (`.impact/coverage.json`, joern pipeline), leak-safe
`//[probe]` instrumentation with marked-line stripping (forced-instrument arm),
`suite_runner` + failure clustering + clean verify, LangGraph orchestration
substrate, and the prepared picocli `putValue`/`addRowValues` experiments. The
MVP is mostly composition, not construction.

## Decisions (locked in brainstorming)

1. **MVP = Lite, single pass.** Alpha → Beta → Gamma → fix; retry ladder
   top-1 → top-2 → DEFER. **Escalation (steps 10–16, Delta/Epsilon/Dzeta,
   trigger subgraph, iterations) is cut** — Phase 2; its nodes are the same
   shapes (refine specs / re-instrument / expand graph), so adding it later is
   additive.
2. **Beta instrumentation = LLM-written `//[probe]`-marked println lines**,
   executed and later stripped by the existing forced-instrument machinery.
   Not bytebuddy (kept as a possible fallback later).
3. **Subgraph filter = distance ≤ 2** from the changed method (+ reachable
   tests). k-medoid deferred; the filter is an isolated node/seam where it
   slots in later.
4. **Memory Graph = a JSON dict** `method_fqn → {causal_graph, test_set, ts}`,
   exact-match keys. Reset per rep inside the A/B (rep independence); the
   hit-rate demo is a separate scripted double run, never mixed into A/B
   metrics.
5. **Implementation = hardcoded LangGraph graph** (`abench/rcc_graph.py`), a
   new orchestration mode `rcc`. The declarative-spec/canvas-editor project
   (2026-07-07 spec) is **parked**; RCC becomes its flagship spec once the
   editor lands (its nodes map to `llm_stage`/`verify` + a tool node).
6. **Internal prompts run on the condition's model** — RCC is a system
   augmentation for the same (weak) model, keeping the A/B contrast clean.
7. **Targets: `putValue` + `addRowValues`** (both prepared in
   `experiments/picocli-putValue/`); demo narrative on `putValue`.

## Non-goals

- No escalation loop, no k-medoid, no statement-level graph granularity, no
  semantic/embedding memory lookup, no multi-method diffs.
- No FCI / noisy-OR / bootstrap / cross-validation / SBFL / PID (per the Lite
  concept's drop table).
- No editor/canvas UI work in this project (trace is visible in the existing
  linear TraceView; the graph overlay arrives with the parked editor project).
- Not a production tool: one language (Java/Gradle), one changed method,
  positive-case demo + honest A/B.

## 1. Placement in the bench flow

A condition `orchestration: rcc` runs: **understand → implement** (the lead
LLM's diff — same phases as `phased`) → suite. If green, finish (RCC never
invoked — recorded as such). If red, the RCC subcycle replaces the plain
diagnose loop. This makes `phased` (the existing diagnose loop) the honest
baseline: same model, same temperature, same understand/implement prefix; the
ONLY contrast is diagnose-loop vs RCC.

## 2. The LangGraph graph

State (`RccState`): `changed_method_fqn`, `subgraph` (methods + edges +
reachable tests), `specs`, `probe_logs`, `causal_graph`, `ranks`, `attempt`
(1|2), `current_diff`, suite results, `memory` (path + dict), `status`
(`SUCCESS` | `DEFER`), degrade flags. Same event/`clock`/`stitch()` discipline
as `orchestrator_graph.py`; every node = a `phase` in trace.json → the linear
TraceView renders the whole run today.

Nodes and edges:

```
check_memory ─(hit)→ fast_fix_from_cache ─(subset green)→ full_suite_cached ─(green)→ save_success
     │(miss)              │(red → invalidate entry)                             │(red → invalidate)
     ▼                    ▼                                                     ▼
build_subgraph → alpha_specs → beta_probe → run_probe_subset → strip_probes → gamma_causal
     → rank → fix_top1 → subset_tests ─(green)→ full_suite ─(green)→ save_success
                              │(red)                 │(red)
                              ▼                      ▼
                        fix_top2 → subset_tests2 ─(green)→ full_suite2 ─(green)→ save_success
                              │(red)                            │(red)
                              ▼                                 ▼
                           defer_exit ◄─────────────────────────┘
```

- **check_memory** — key = target method FQN. Hit → `fast_fix_from_cache`
  (fix prompt gets the cached causal graph + current failing state; runs the
  cached `test_set` subset, then full suite). Stale (tests fail) → delete the
  entry, controller event, continue to the full pass. Miss → full pass.
- **build_subgraph** — from `.impact/coverage.json` (method→tests; the
  joern-precomputed neighborhood around the targets) + `methods.json` (source
  spans): the changed method + neighbors ranked by covering-test overlap with
  it, top-K (default 5), plus the union of their covering tests. Deterministic,
  no LLM. (Amended from "call-graph distance ≤ 2": no explicit method→method
  edge artifact exists; test-set overlap over the precomputed neighborhood is
  the MVP filter — the node stays the seam for k-medoid/edge-based filters.)
- **alpha_specs** — ONE LLM call for the whole subgraph (≤ ~8 methods), not
  per-method. The answer (pre/post/invariants per method) is kept as ONE text
  block passed downstream — no per-method JSON parsing (fewer parse-failure
  modes; Gamma consumes text anyway).
- **beta_probe** — LLM stage with edit tools: insert println lines, each
  suffixed `//[probe]`, at points it chooses (entry/exit/branches, local
  variables visible). Compile check; on failure one repair attempt (the agent
  sees the compiler error), then **degrade**: strip probes, continue without
  logs (flag recorded — Gamma runs on specs+graph only).
- **run_probe_subset** — run ONLY the subgraph's tests with probes in place;
  capture stdout probe lines into `probe_logs` (per-method grouping).
- **strip_probes** — remove `//[probe]` lines from the working tree
  (existing strip machinery) so all later stages and diffs are clean.
  Belt-and-braces: final-diff extraction also strips (as in the
  forced-instrument arm) — probes can never leak into results.
- **gamma_causal** — ONE LLM call: (subgraph, specs, probe_logs) → JSON
  `{nodes, edges}` with `type ∈ {calls, data_dep, causal}`, `weight ∈ [0,1]`,
  `reason` per causal edge. Parse failure → one re-ask with a format reminder →
  degrade to rank = call-graph distance (event recorded).
- **rank** — CausalRank(m) = Σ weights of causal edges leaving m; sort.
  Record `rcc_root_rank` = position of the known true root (ground truth per
  target) for APFDc.
- **fix_top1 / fix_top2** — LLM stage: causal graph + specs + failing tests +
  current diff, focused on the top-k method; produces the new patch in the
  working tree.
- **subset_tests / full_suite** — subset = the subgraph's tests via Gradle
  test filtering (`--tests` patterns; reuse `graph_cover._norm_key` mapping);
  full = the standard `suite_runner` (clean verify semantics, undercount
  guard).
- **save_success** — write `{causal_graph, test_set, ts}` to the memory file;
  outcome `green`.
- **defer_exit** — outcome `stuck` (DEFER); the last attempted diff remains in
  the tree (bench diffs/verify record it as usual).

## 3. New vs reused

Reused as-is: `phase_runner` (opencode), `suite_runner`, `cluster_failures`,
`stitch`, coverage/impact pipeline, `//[probe]` strip machinery, runner
condition plumbing, TraceView, metrics/diff/verify.

New modules:
- `abench/rcc_graph.py` — state, nodes, `run_rcc(...)` (same injected-deps
  signature style as `run_graph`).
- `abench/rcc_subgraph.py` — coverage + call-graph → distance≤2 subgraph +
  test set (pure, unit-testable).
- `abench/rcc_prompts.py` — Alpha/Beta/Gamma templates + Gamma JSON parsing.
- `abench/rcc_memory.py` — load/save/invalidate the memory JSON (path in the
  run layout; A/B runs get a fresh file per rep).
- `suite_runner` extension: optional test-filter parameter (subset runs).
- Config: `orchestration: rcc` in the condition Literal (+ its knobs:
  `rcc_max_attempts=2`, memory path override for the hit-demo).

## 4. The experiment (honest by construction)

- **A/B:** `phased` vs `rcc`; same model + temperature; N reps; targets
  `putValue` and `addRowValues`. Primary metrics — the bench's existing ones:
  fix rate (outcome green), suite runs, tokens/cost, wall time.
- **Secondary:** APFDc from `rcc_root_rank` (ground-truth root known per
  target); `rcc_memory_hit`, `subset_test_runs`, degrade-flag counts — all
  added to metrics extraction.
- **Memory validity:** fresh memory per rep in A/B (no cross-rep leakage).
  Hit-rate/cycle-time-reduction demo = a separate script: run the same target
  twice against one persistent memory file; expect run 2 to take the
  fast path (hit rate 1.0, large wall-time drop). Reported separately from
  the A/B, explicitly labeled.
- **Leak safety:** probes stripped from every final diff; the causal graph and
  specs are generated from code the agent can legitimately see; no GT
  artifacts enter prompts (same discipline as the forced-instrument arm).

## 5. Error handling

- Beta broke the build → 1 repair attempt → degrade to no-logs Gamma
  (controller event + flag; run continues). Statuses stay SUCCESS/DEFER;
  hard FAIL only for infrastructure errors (compile broken even after probe
  strip, suite runner crash) — surfaced like today's service errors.
- Gamma unparseable twice → distance-based ranking fallback (event + flag).
- Cache-hit path failing tests → invalidate entry + full pass (never trust a
  stale insight).
- Every degrade is a controller event → visible in TraceView and countable in
  metrics (the "LLM couldn't follow the format" failure mode is measured, not
  hidden).

## 6. Testing

- Unit: `rcc_subgraph` (fixture coverage + edges → expected neighborhood/test
  set); CausalRank + `rcc_root_rank`; memory hit/miss/stale semantics; Gamma
  JSON parse + both degrade paths; test-filter pattern building.
- Graph-level on fakes (the `orchestrator_graph` parity-test style: canned
  phase outputs, scripted suite results): green-on-top1, top2-rescue, defer,
  memory-hit fast path, stale-cache invalidation, beta-compile-fail degrade,
  gamma-parse degrade.
- E2E smoke on the prepared machine: 1 rep of `rcc` on `putValue`, inspect the
  trace end-to-end (probe lines visible in phase turns, absent from the final
  diff).

## Rollout — two implementation plans

1. **Core loop:** rcc_subgraph + prompts + rcc_graph + subset runner + memory
   + the fake-based graph tests.
2. **Experiment wiring:** condition/config plumbing, metrics additions
   (APFDc, hit/degrade counters), the hit-demo script, A/B experiment YAMLs
   for both targets, e2e smoke.

## Risks / open items

- Weak models may botch probe insertion or Gamma JSON — mitigated by repair
  retry + degrade paths, and measured as flags (that's itself experimental
  signal, not noise).
- `coverage.json` freshness: regenerated by the existing impact pipeline
  during experiment prepare (already part of the picocli setup).
- Gradle `--tests` filtering with parameterized/nested tests — reuse the
  `_norm_key` normalization; verify subset counts against expected
  (executed≈expected guard applies to subsets too).
- Phase-2 seams kept deliberately: filter node (k-medoid), retry ladder →
  escalation subgraph, exact-match memory → semantic lookup.

## Self-review

- Placeholder scan: none; all deferrals are named and scoped (escalation,
  k-medoid, editor UI, semantic memory).
- Consistency: the top-1→top-2→DEFER ladder, memory-reset rule, and the
  degrade-not-fail philosophy are stated once each and used consistently.
- Scope: two plans; composition over construction; the editor project is
  explicitly parked, not entangled.
- Ambiguity: instrumentation mechanism (println `//[probe]`), baseline
  (`phased`), internal-prompt model (condition's model), and memory validity
  rules are each pinned to a single behavior.
