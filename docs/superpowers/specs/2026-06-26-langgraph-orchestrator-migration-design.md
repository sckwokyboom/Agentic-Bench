# LangGraph orchestrator migration — design

**Date:** 2026-06-26
**Status:** approved (brainstorming) → next: implementation plan

## Motivation

The phased controller (`abench/orchestrator.py::run`) is hand-rolled control flow.
This session it produced real, costly bugs (revert-to-best freezing the agent at
the stub; stale failure clusters; observability gaps) — symptoms of ad-hoc state
management. The goal is a **research program over orchestration strategies** (how
to sequence the agent, which tools, which augmentations, branching, multi-agent).
For that program, a clean, flexible, explicit-state orchestration substrate lowers
the per-variant engineering cost and bug surface.

**LangGraph is an infrastructure/iteration-velocity lever, NOT a quality lever.**
It will not raise the benchmark metric or fix the weak model's capability — those
depend on the operating regime + whether augmentations carry the decisive signal.
LangGraph makes *trying* orchestration hypotheses faster and cleaner. We adopt it
for that reason, clear-eyed.

## Decisions (locked in brainstorming)

1. **opencode stays the agent.** Driver = orchestration flexibility, not owning the
   loop. opencode keeps providing the agent loop, tool execution, docker sandbox,
   provider adapters, event→Trace normalization, and stall/loop/timeout/rate-limit
   handling. LangGraph replaces ONLY our phase controller (`orchestrator.py`).
2. **Approach A — thin graph over existing adapters.** Graph nodes call the
   unchanged adapters (`phase_runner` = opencode `run_task`, `suite_runner` =
   gradle, `cluster_failures`, `build_*_card`). The graph replaces only the
   control-flow + state of `run()`.
3. **Parity-first.** First milestone: reproduce the current forward-only phased on
   LangGraph 1:1, validate equivalence by trace/metrics, keep `orchestrator.py`
   alongside until cutover. New orchestration variants come after parity.

## Non-goals

- Not replacing opencode (no owning the agent loop now).
- Not changing the `Trace` schema, metrics, or UI — comparability must hold.
- Not building new orchestration variants yet (parity is the milestone).
- No refactor of `orchestrator.py` (it stays working + is the default).

## 1. State schema

A `StateGraph` over a typed `OrchState` (TypedDict) holding exactly what flows
between steps of `run()` today. Injected externals are bound into nodes via a
`build_graph(cfg, phase_runner, suite_runner, in_blast_radius, read_evidence,
on_event)` factory — NOT state — mirroring today's injected-deps pattern (keeps the
graph testable with fakes and signature-comparable to `run()`).

Fields:
- `cfg: OrchestratorConfig` — read-only (target_label, contract_fields,
  max_diagnose_iters, no_progress_limit, cluster_cap, with_plan).
- `contract: str`, `plan: str` — phase outputs.
- `cur: SuiteEval` — the LATEST suite result; current failures live here (→ clusters, card).
- `card: str | None` — latest runtime-evidence card.
- `it: int`, `no_progress: int` — diagnose-loop counters.
- `best_failed: int | None`, `productive: int` — passive analytics.
- `phase_traces: Annotated[list[tuple[str, Trace]], add]` — per-phase opencode traces (append-reducer).
- `ctrl: Annotated[list[Step], add]` — controller events (append-reducer).
- `test_runs: int`, `clock: float` — counters (controller-event ts + suite-run count).
- `outcome: str | None` — set at finalize.

Mutation model: append-lists (`phase_traces`, `ctrl`) use add-reducers (a node
returns only the new items); scalars are overwritten by node returns. `on_event`
(live-viz) is a side-effect inside a node, not state.

**Constraint:** at finalize the graph calls the SAME
`stitch(phase_traces, ctrl, outcome=…, accepted_rounds=productive,
reverted_rounds=0, best_failed_reached=best_failed)` → identical Trace schema →
metrics/UI/comparability unchanged.

## 2. Nodes + edges

Nodes (each calls existing adapters — no new logic):
- **baseline** — `suite_runner()` on the stub → init `cur`, `best_failed`; baseline event.
- **understand** — `do_phase("understand")` → `contract` (or `fallback_contract`); event.
- **plan** — `do_phase("plan")` → `plan`; event. *(entered only if `cfg.with_plan`)*
- **implement** — `do_phase("implement")` → `suite_runner()` → `cur`, `_track_best`; event.
- **diagnose** *(one round)* — `it += 1`; `card = read_evidence()` (if set);
  `cluster_failures(cur.failures)` [+ graph-focus if `in_blast_radius`];
  `do_phase("diagnose", diagnose_prompt(…, clusters, card))`; `suite_runner()` →
  `cur`, `_track_best`, update `no_progress`; event.
- **finalize** — compute `outcome` from `cur`; event. (`stitch(…)` runs in the
  `run_graph` wrapper after the graph returns the final state.)

Edges:
```
START → baseline → understand
understand ─(cond)→ plan | implement       # plan only if with_plan
plan → implement
implement ─(cond)→ diagnose | finalize     # finalize if already green
diagnose ─(cond)→ diagnose | finalize      # CYCLE while not green & it<max & no_progress<limit
finalize → END
```
`continue?` predicate: `not (cur.compiled and cur.failed == 0) and it <
max_diagnose_iters and no_progress < no_progress_limit` → `diagnose`, else
`finalize`. Forward-only: no reverts; `cur` only moves forward (as today).

**One graph covers all current phased modes.** phased / phased_plan / phased_graph
/ phased_runtime differ only by bound deps (`with_plan`, `in_blast_radius`,
`read_evidence`) — exactly like `run()` today. Parity = the graph reproduces
`run()` for any combination of these.

## 3. Switch (Python ↔ graph) + trace-equivalence

New module `abench/orchestrator_graph.py` with
`run_graph(cfg, *, phase_runner, suite_runner, snapshot, restore, on_event,
in_blast_radius, read_evidence) -> Trace` — SAME signature as `orchestrator.run`.
Internally: `build_graph(…)` binds deps into nodes → compiles the `StateGraph` →
invokes it → calls `stitch(…)` on the final state → returns the Trace.

Runner switch (one line; rest of the runner unchanged):
```python
_orchestrate = run_graph if os.environ.get("ABENCH_ORCHESTRATOR") == "langgraph" else orchestrator.run
```
Signatures are identical → drop-in. experiment.yaml condition definitions are
unchanged → the SAME condition runs through either orchestrator by flag → traces
compared.

Trace-equivalence target (both call the same `stitch`): same `outcome`; same
metrics (`n_steps`, `productive`/`accepted_rounds`, `reverted_rounds=0`,
`best_failed_reached`); same controller-event texts in order; same `phase_traces`
structure. Discipline: nodes emit EXACTLY the same events (texts, order) and use
the same `clock` counter (ts) as `run()` → `stitch` (sort by ts) yields an
identical Trace. The graph is sequential (no parallelism) + append-reducers
preserve order → deterministic.

## 4. Location + dependencies

Files:
- `abench/orchestrator_graph.py` (NEW) — `OrchState`, nodes, `build_graph`,
  `run_graph`. **Imports the shared pure helpers** from `orchestrator.py`
  (`understand_prompt`, `plan_prompt`, `implement_prompt`, `diagnose_prompt`,
  `contract_ok`, `plan_ok`, `fallback_contract`, `_track_best`, `_cap`) +
  `cluster_failures`/`select_clusters` (failure_report) + `stitch` (trace_stitch).
  → prompts/gates/tracking/stitch are single-sourced; only control-flow differs.
- The thin wrappers (`do_phase` = announce+phase_runner+degrade, `run_suite` =
  count+catch, `event` = build Step + emit) are ~3-5 lines each, reimplemented
  inside the graph module. If they ever drift from `run()`, extract to a shared
  `orchestration_common.py` — not needed now; the parity test catches drift.
- `orchestrator.py` (Python `run()`) — untouched; remains the default. The graph is
  additive + opt-in.

Dependencies:
- `langgraph` as an OPTIONAL extra (`abench[langgraph]`), version-pinned. We use a
  narrow surface — `StateGraph` + reducers only; NOT LangChain's model/tool
  abstractions (the agent is opencode).
- **Lazy import** inside `run_graph`/`build_graph` → the default Python path does
  not require langgraph installed; selecting the graph without it → a clear error.

Effect on the rest: Trace schema unchanged → metrics/UI/web bundle unchanged.
Deploy for the graph path: `git pull` + `pip install -e .[langgraph]` + restart;
the default path is unaffected.

## 5. Parity testing

Unit parity (fast deterministic gate): reuse the fakes from `test_orchestrator.py`
(`_fake_phase`, `_fake_suite`, `_CFG`, `_CONTRACT`, `in_blast_radius`/
`read_evidence` lambdas). New `tests/test_orchestrator_graph_parity.py`: for each
scenario, run BOTH `run()` and `run_graph()` on the same fakes and assert Trace
equivalence on: `orchestration_outcome`; `accepted_rounds`/`reverted_rounds`/
`best_failed_reached`; the ordered list of controller-event texts;
`metrics.extract` key fields (`n_steps`, …); `phase_traces` count/structure. Cover
the same scenarios that already exist for `run()`: green-on-implement,
green-after-1-diagnose, stuck (no_progress stop), never-reverts (`restores==0`),
fallback-contract, graph-focus, runtime-card, failing phases/suite.
`pytest.importorskip("langgraph")` → skips cleanly without the extra.

E2E smoke (real confirmation, on WSL): run one condition twice —
`ABENCH_ORCHESTRATOR=python` then `=langgraph` — and compare the two `trace.json`
(outcome + metrics + controller events). Parity with real opencode/gradle.

**Cutover criterion:** unit parity green + e2e smoke matching on one real condition
(e.g. `phased`) → trust the graph → flip the default and proceed to new
orchestration variants.

## Risks / open items

- **Event/ts ordering drift:** the graph must emit controller events in the same
  order + with the same `clock` ts as `run()`, else `stitch`'s ts-sort diverges.
  Mitigation: the parity test asserts the ordered event-text list; fix any drift.
- **LangGraph add-reducer ordering:** relied upon to preserve cross-node append
  order. Safe because the graph is sequential; documented + parity-tested.
- **First post-parity variant is undecided.** The graph is built generically
  (typed state + conditional edges); the first new orchestration variant (branching
  / multi-agent / oracle-centric augmentation injection) is chosen after parity.

## Self-review

- Placeholder scan: none (no TBD/TODO; all sections concrete).
- Consistency: opencode-stays + thin-graph + parity-first are coherent across all
  sections; the Trace/stitch constraint is repeated and consistent.
- Scope: focused on the parity milestone (one graph reproducing `run()`); new
  variants explicitly deferred → single-plan-sized.
- Ambiguity: the wrappers' "reimplement vs extract" is resolved (reimplement now,
  extract only on drift); the switch mechanism (env var) is explicit.
