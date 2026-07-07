# Orchestration graph: declarative spec + canvas editor — design

**Date:** 2026-07-07
**Status:** approved (brainstorming) → next: implementation plan (phase 1)

## Motivation

The research program is *orchestration strategies*: how to sequence the agent,
which prompts, which tools, where to loop. The LangGraph parity milestone landed
(`abench/orchestrator_graph.py`, per-condition `engine` switch, 10 scenarios
equal-by-trace) — the substrate exists, but authoring a NEW strategy still means
writing Python. This project makes strategies **data**: a declarative graph spec
(nodes = stages, edges = conditional transitions incl. cycles), compiled to a
LangGraph `StateGraph`, executed by the existing runner, authored in a
ComfyUI-style canvas editor, and analyzed per-run via an execution overlay on the
same canvas. Example target strategy (drives the design): println-probes →
analyze outputs into a knowledge graph → generate the target method body →
run the suite → green ? finish : loop back.

## Decisions (locked in brainstorming)

1. **Core = declarative spec compiled to LangGraph.** The canvas editor is the
   primary authoring surface; JSON is the storage format, not a milestone of its
   own. Deliverable = format + compiler + editor together.
2. **Topology source of truth = the spec.** The run's trace embeds a full copy
   of the spec it executed → the trace view renders exactly the graph that ran.
   No hand-drawn per-mode pictures in the frontend.
3. **Data flow = shared state (blackboard), LangGraph-style.** Prompts are
   templates with `{field}` placeholders; edges carry control flow + predicates
   only. Port-style dataflow (literal ComfyUI) rejected: ComfyUI is a DAG and
   cycles are first-class here.
4. **Node palette v1: `llm_stage` + `verify` (+ `finish`).** Shell / analytics /
   multi-agent / LLM-judge nodes deferred; the format leaves room (node `type`).
5. **Edge conditions = fixed predicate set** with and/or/not combinators. No
   free-form expressions, no LLM-judge routing (deferred until a concrete need).
6. **opencode stays the agent** (per 2026-06-26 spec). Spec nodes bind to the
   existing adapters (`phase_runner`, `suite_runner`); trace/metrics/verify and
   A/B comparability are preserved via the same `stitch()`.
7. **Order:** this project first; trace-visualizer enrichment (markdown render,
   syntax highlight, diff view) is a separate parallel spec.

## Non-goals

- No live in-flight overlay in this project (post-hoc traces first; a live
  current-node highlight over the existing WebSocket is a later increment).
- No shell/analytics node types in v1.
- No Trace-schema changes beyond additive fields.
- Not replacing opencode; not touching `orchestrator.py` (legacy modes keep
  working unchanged).
- Trace-visualizer enrichment (rich rendering) is out of scope here.

## 1. Spec format

JSON documents. Built-ins ship at `abench/orchestrations/*.json` (read-only in
the UI — duplicate to edit); user library at `orchestrations/*.json` in the repo
root (git-versioned), CRUD through the web API.

Abridged example (the println cycle):

```json
{
  "name": "println-cycle",
  "description": "Invasive-debug loop: probes → KG → generate → verify",
  "version": 1,
  "state": [
    {"name": "probes_output",   "kind": "text"},
    {"name": "knowledge_graph", "kind": "text"},
    {"name": "putValue_body",   "kind": "text"},
    {"name": "test_report",     "kind": "suite"}
  ],
  "entry": "probes",
  "nodes": [
    {"id": "probes",  "type": "llm_stage", "label": "println debug",
     "prompt": "Insert println probes …", "tools": ["read", "edit", "bash"],
     "writes": "probes_output", "model": {"temperature": 0.2}, "on_error": "abort"},
    {"id": "analyze", "type": "llm_stage", "label": "analyze → KG",
     "prompt": "Build a knowledge graph from: {probes_output}",
     "tools": ["read", "bash"], "writes": "knowledge_graph"},
    {"id": "generate", "type": "llm_stage", "label": "generate putValue",
     "prompt": "Generate the body. Analysis: {knowledge_graph}\nLast feedback: {test_report}",
     "tools": ["read", "edit"], "writes": "putValue_body"},
    {"id": "tests", "type": "verify", "writes": "test_report"},
    {"id": "done",  "type": "finish"},
    {"id": "stuck", "type": "finish", "outcome": "stuck"}
  ],
  "edges": [
    {"from": "probes",   "to": "analyze"},
    {"from": "analyze",  "to": "generate"},
    {"from": "generate", "to": "tests"},
    {"from": "tests", "branches": [
      {"when": {"kind": "tests_green"}, "to": "done"},
      {"when": {"kind": "node_iters_lt", "node": "probes", "n": 5}, "to": "probes"}
    ], "else": "stuck"}
  ],
  "limits": {"max_node_visits": 50},
  "ui": {"nodes": {"probes": {"x": 12, "y": 28}}}
}
```

**State fields.** `kind: text` — the stage's final assistant text is written
verbatim. `kind: suite` — a verify result (SuiteEval + failure clusters).
Placeholder rendering: text inserts verbatim; suite inserts the human-readable
failure summary + clusters (the same formatter today's diagnose prompt uses).
A field not yet written renders as an explicit `"(not available yet)"` marker —
this is defined behavior, so first-iteration prompts that reference loop
feedback are legal.

**Nodes.**
- `llm_stage`: `prompt` template, `tools` scope (the same per-phase opencode
  tool gating as today), `writes` (one declared field), optional `model`
  overrides (`temperature` now; model id later), `on_error: abort | continue`
  (default `abort`).
- `verify`: `suite_runner()` + `cluster_failures()`; writes a `suite` field;
  updates the automatic trackers (`best_failed`, `no_progress`).
- `finish`: terminal. Optional `outcome` override (e.g. `"stuck"`). Default
  outcome derives from the last suite eval: `green` if compiled and 0 failed,
  else `compile-fail`/`red`; a limits stop yields `budget`.

**Edges.** Per node exactly one outgoing rule: either unconditional
`{from, to}` or branching `{from, branches: [{when, to}…], else}` (`else`
required). Predicates:
- `{"kind": "tests_green"}` — last suite eval compiled and 0 failed
- `{"kind": "compiled"}`
- `{"kind": "node_iters_lt", "node": id, "n": N}` — automatic per-node visit counter
- `{"kind": "no_progress_lt", "n": K}` — consecutive suite evals without improvement < K
- combinators `{"all": […]}`, `{"any": […]}`, `{"not": …}`

**Limits.** `max_node_visits` (global backstop, default 50). Wall-clock remains
the runner's existing timeout.

**`ui`.** Canvas coordinates per node; ignored by the compiler.

**Validation** (single authoritative implementation in Python; a cheap TS
mirror gives instant editor feedback; the server endpoint is the gate):
- every `{placeholder}` names a declared state field (error);
- a read field should be written on some entry→reader path (warning — the
  `"(not available yet)"` rendering makes first-pass reads legal);
- all nodes reachable from `entry`; some `finish` reachable from every node (error);
- every cycle must contain at least one branch bounded by `node_iters_lt` /
  `no_progress_lt` (error) — `max_node_visits` is the runtime backstop, not an
  excuse for unbounded cycles;
- `writes` names a declared field; branching edges have `else` (error).

## 2. Compiler + execution

New modules:
- `abench/graph_spec.py` — pydantic models + the validation above (load,
  validate, canonical JSON).
- `abench/graph_compile.py` — `run_spec_graph(spec, cfg, *, phase_runner,
  suite_runner, on_event, …) -> Trace`. Reuses the discipline proven in
  `orchestrator_graph.py`: dict state with append-reducers for
  `phase_traces`/`ctrl`, the same event/`clock` conventions, the same
  `stitch()` at finalize. `llm_stage` = render prompt from state →
  `do_phase(node.id, prompt, tools, model overrides)` via `phase_runner`
  (opencode `run_task`); `verify` = suite + clusters + trackers; branching
  edges compile to LangGraph conditional edges evaluating predicates over
  state; `finish` → outcome + END.

**Trace.** `phase` = node id → the linear TraceView (PhaseDivider, TurnCards)
works unchanged. Additive fields: `orchestration_spec` (embedded full copy —
the trace is self-contained even if the spec is edited later) and
`node_visits` (per-visit journal for the overlay). Everything else unchanged →
metrics/verify/A-B untouched.

**Config/runner wiring.** Condition gains optional `orchestration_spec: str`
(name of a built-in or saved spec), mutually exclusive with the `orchestration`
mode Literal. When set, `_select_orchestrator` loads + validates + compiles the
spec and runs it on the LangGraph engine (requires `abench[langgraph]`; clear
error otherwise). Legacy modes and engines stay untouched.

**Built-ins + parity (the correctness gate).** `phased` and `phased_plan` are
re-expressed as built-in specs. The existing 10-scenario parity suite gains a
third contestant: `run_spec_graph(built-in phased spec)` must be equal-by-trace
with `orchestrator.run` and `run_graph` on the same fakes. Compiler correct ⇔
parity green. **Explicit deferral:** `phased_graph` and `phased_runtime` need
context providers (call-graph focus, runtime-evidence card) that v1 specs
cannot express — those two modes stay on the legacy engines until a
context-provider design exists.

**API** (`abench_ui/server.py`): `GET /api/orchestrations` (built-ins + user
library), `GET/PUT/DELETE /api/orchestrations/{name}`,
`POST /api/orchestrations/validate` (issues without saving). Built-ins are
read-only (write → 409; UI offers Duplicate).

## 3. Canvas editor (web)

- Dependency: `@xyflow/react` (react-flow v12) — the standard React substrate
  for ComfyUI-like canvases (drag nodes, drag-to-connect, pan/zoom).
- Routes: `/orchestrations` (library: cards with name, description, node count,
  which experiments reference it) and `/orchestrations/:name` (editor).
- `web/src/lib/specGraph.ts` — pure spec ↔ react-flow mapping (nodes, edges,
  positions), unit-tested round-trip.
- Custom node components: `LlmStageNode` (type chip, label, reads/writes
  badges, prompt preview), `VerifyNode`, `FinishNode`.
- Inspector drawer (right, on node select): label; prompt editor — monospace,
  placeholder chips highlighted, autocomplete over declared fields, fullscreen
  expand (prompts are long); tools multiselect (same source as ToolsSelect);
  `writes` select; temperature override; `on_error`.
- Edge panel (on edge/source select): if / else-if / else predicate builder —
  predicate dropdowns with params, and/or grouping, target selects, terminal
  branch outcome pick.
- Toolbar: name, live validation chip (instant local checks + debounced server
  validate), Save, Duplicate, Delete. Invalid specs CAN be saved as drafts —
  editing momentum matters — but a run refuses to start on an invalid spec
  (fail-fast with the validation report, before any docker/agent spin-up).
- ExperimentEdit: OrchestrationSelect grows a "saved graphs" group that sets
  `orchestration_spec`.

## 4. Run overlay in TraceView

For traces carrying `orchestration_spec`, TraceView gains a **Graph** tab
(linear view remains the default). The same canvas, read-only, with execution
facts on top: per-node visit count (×N), Σ tokens/cost per node, last-visit
status (ok / failed / degraded); cycle edges show taken-count; never-taken
edges/nodes dimmed. Clicking a node opens a drawer listing its visits — each
with the exact rendered prompt captured in the trace (`phase_prompt` steps),
the response summary, per-visit suite delta for verify nodes, and a jump-link
to that spot in the linear trace. Live current-node highlight: deferred
increment (WS infra exists).

## 5. Error handling

- Spec load/validation failure at run start → fail fast with the report.
- `llm_stage` failure (opencode error/timeout): `abort` → controller event +
  finalize with outcome `error`; `continue` → writes
  `"(stage failed: reason)"` into its field and follows normal edges.
- `max_node_visits` exceeded → finalize with outcome `budget` (controller
  event records the limit).
- Editor surfaces server validation as a banner list; offending nodes/edges get
  a red outline.

## 6. Testing

- `graph_spec`: schema + one unit test per validation rule.
- `graph_compile`: (a) parity — built-in `phased`/`phased_plan` specs vs
  `orchestrator.run` and `run_graph` on the existing fakes/scenarios (extend
  `tests/test_orchestrator_graph_parity.py`); (b) the println-cycle fixture on
  fakes: loop iterates, predicates route, limits stop, unwritten-field
  rendering, both `on_error` modes.
- API: CRUD, built-in immutability, validate endpoint (existing FastAPI test
  patterns).
- Web: specGraph round-trip; inspector edits → correct spec mutations;
  validation display (vitest, existing patterns).
- E2E smoke on the prepared machine: one real condition run with
  `orchestration_spec: phased` vs `orchestration: phased` (python engine) —
  equal outcome/metrics. This doubles as the real-world cutover confirmation
  the 2026-06-26 spec left pending.

## Rollout — three implementation plans

1. **Backend core:** spec format + validation + compiler + parity + condition
   wiring + API CRUD.
2. **Editor UI:** library, canvas, inspector, edge panel, validation UX,
   experiment integration.
3. **Trace overlay:** trace additions (spec embed + `node_visits`), Graph tab,
   per-node visits drawer.

## Risks / open items

- `phased_graph`/`phased_runtime` context providers are explicitly out of v1;
  those modes stay on legacy engines. A "context provider" node/attachment
  design is the natural follow-up once the base ships.
- The predicate set may prove too narrow for the research program — the
  extension point is the predicate registry in `graph_spec.py`; free-form
  expressions stay excluded until a concrete need shows up.
- react-flow is a sizeable web dependency — acceptable for a dev-tool UI; no
  effect on benchmark validity.
- Spec evolution: `version` field + a loader migration hook from day one.

## Self-review

- Placeholder scan: none — every section is concrete; deferrals are explicit
  (context providers, live overlay, shell nodes), not vague.
- Consistency: blackboard-state + control-flow-edges is applied uniformly
  (format, compiler, editor, overlay); the stitch/Trace constraint matches the
  2026-06-26 spec it builds on.
- Scope: one system, three plans; parallel trace-enrichment work is explicitly
  a separate spec.
- Ambiguity: unwritten-field rendering, draft-save vs run-gate, and the
  parity scope (phased + phased_plan only) are each pinned to one behavior.
