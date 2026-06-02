# Trace rendering + verify build/test correctness — design spec

**Date:** 2026-06-01
**Status:** approved-in-principle (brainstorm); user reviewing this spec
**Builds on:** the shipped Web UI, the verify subsystem (`abench/verify.py`), trace
normalization (`abench/trace_normalize.py`), and metrics (`abench/metrics.py`).

## Problem

Two correctness defects make the UI unfit for analyzing agent chains:

1. **Trace metrics are all zero / garbled.** The frontend re-parses the raw
   `events.jsonl` against a **guessed** event shape (`part.type === "tool-call"`,
   `part.name`, `part.input`). The REAL OpenCode shape (verified in
   `trace_normalize.py` and `tests/fixtures/opencode/events_sample.jsonl`) is
   `part.type === "tool"`, `part.tool`, `part.callID`, `part.state.{status,input,output}`,
   `part.state.metadata.exit`, plus `part.type === "patch"` for file edits and
   `step-finish` for tokens/cost. So tool/read/search/edit counts never match → all
   zero; file edits are ignored; per-turn stats render as cryptic "11.7k/118 tok · $…".
   Meanwhile the backend ALREADY normalizes correctly into `trace.json`
   (`steps` + `turns`) and `metrics.json` (`n_tool_calls`/`n_reads`/`n_searches`/
   `n_files_edited`) — the right data exists; the frontend renders from the wrong
   source with the wrong schema.

2. **Build-system detection is wrong and unconfigurable.** `verify.detect_command`
   checks `pom.xml` before Gradle, so a Gradle project carrying a stray root
   `pom.xml` (e.g. picocli) is mis-detected as Maven → `mvn test` → errors. Auto-detect
   is a heuristic that will sometimes be wrong, and there is no usable way to override
   it in the UI (the `verify.command` field renders as a meaningless rjsf `anyOf`
   dropdown). The user cannot control or correct how the project builds/tests.

## Goals

Make a finished trace render correctly (real tool calls + args + results + exit codes,
file edits, readable per-turn stats, authoritative process metrics, test results), make
the **live** run stream render the real event shape too, and make verify **actually run
the right build/test command** — with smarter detection, explicit ambiguity surfacing,
and a usable override in the UI. Verify all of this with **real** Gradle/Maven builds
(toolchain is available on the dev machine).

## Non-goals (separate later cycles)

- Full experiment-form rework (collapse all `anyOf`, descriptions everywhere, "Advanced"
  section for metrics knobs) — workstream **A**, later. This spec touches only the
  **verify** fields of the form.
- Side-by-side trace comparison (the Results page already compares metrics in aggregate).
- verify Phase-2 (two-phase build/test separation; prompt injection).

---

# Part 1 — Trace rendering correctness (workstream C)

## Real OpenCode event shape (authority: `trace_normalize.py` + the fixture)

| part.type | fields the UI needs |
|---|---|
| `tool` | `tool` (name), `callID`, `state.status` ("completed"/"error"), `state.input` (args dict), `state.output` (str), `state.metadata.exit` (int\|null), `state.time.{start,end}` (ms) |
| `text` | `text`, `time.start` |
| `reasoning` | `text` |
| `patch` | `path`, `patch` (file edit) |
| `step-finish` | `tokens.{input,output,reasoning}`, `cost`, `reason`, `time.{start,end}` |
| `step-start` | (skip) |
All carry `part.messageID` (turn grouping).

The backend `normalize()` maps this into `Trace.steps` (`Step{kind ∈ TOOL_CALL,
TOOL_RESULT, REASONING, ASSISTANT_TEXT, FILE_EDIT; ts; turn; tool_name; tool_args;
output; exit_code; text; path; patch; tool_call_id}`) and `Trace.turns`
(`TurnInfo{message_id, reason, tokens_in, tokens_out, tokens_reasoning, cost,
started_at, ended_at}`).

## Approach (recommended): render finished traces from the normalized `trace.json`

The backend normalizer is the single, fixture-tested source of truth and already backs
`metrics.json`. So:

- **Finished TraceView** renders the turn timeline from `trace.steps` + `trace.turns`,
  and the aggregate header from `metrics.json` (authoritative numbers, identical to the
  CLI). No TS re-parse of the raw shape → no drift.
- **Live Run page** (no normalized trace mid-run) uses a thin, well-tested TS
  normalizer `normalizeRawPart(part)` that maps the REAL raw shape into the same shared
  UI model the timeline consumes. Both sources feed one render path.

### Shared UI model

```ts
type UiPartKind = "reasoning" | "tool" | "text" | "edit";
interface UiToolPart {
  kind: "tool"; name: string; args: Record<string, unknown>;
  output: string | null; exitCode: number | null; ok: boolean | null; // status/exit derived
}
interface UiTextPart  { kind: "reasoning" | "text"; text: string; }
interface UiEditPart  { kind: "edit"; path: string; patch: string; }
type UiPart = UiToolPart | UiTextPart | UiEditPart;
interface UiTurn {
  index: number; messageId: string | null;
  reason: string | null; tokensIn: number | null; tokensOut: number | null;
  cost: number | null; durationS: number | null;
  parts: UiPart[];
}
```
- `web/src/lib/traceModel.ts`: `turnsFromTrace(trace)` (groups `trace.steps` by `turn`,
  pairs TOOL_CALL+TOOL_RESULT by `tool_call_id`, joins `trace.turns`) and
  `turnsFromRawEvents(rawEvents)` (groups by `part.messageID`, maps the real raw shape).
  Both return `UiTurn[]`.

### Types

Add a TS `Step` type mirroring the backend `Step` and `steps: Step[]` to `Trace`
(`web/src/api/types.ts`). `StepKind` string-union.

### Turn timeline (TurnCard, rewritten to render `UiTurn`)

Per part: 💭 reasoning (collapsible >600 chars); **tool** = `name` + a short args summary
(prefer `command`/`filePath`/`path`/`pattern` from `args`, else compact JSON) + output
snippet + `✓/✗` by `exitCode`/`ok`; 🗨 text; 📝 edit = `path` + a few `patch` lines.
Per-turn footer: **breakdown by real tool name** ("read ×3 · grep ×2 · edit ×1 ·
bash ×1") computed from this turn's tool parts (no fixed read/grep/edit buckets), plus
readable stats: `in {tokensIn} · out {tokensOut} · ${cost} · {durationS}s` with labels.

### Aggregate header (authoritative + test results)

A labeled stats bar fed by `metrics.json` (`useMetrics` on TraceView): steps, tool calls,
reads, searches, test runs, files edited, tokens in/out, cost, time-to-first-edit — each
with a one-line tooltip of what it means. The verify result (passed/failed/total + which
failed) stays prominent at top via the existing `VerifyBanner`/`VerifyCard`.

### Metrics enrichment (the comparison signals the user asked for)

The OpenCode data carries more than is currently captured (verified in the fixture:
`info.tokens = {input, output, reasoning, cache:{read, write}}`). Add these analysis
signals:

**Backend:**
- `trace_normalize.normalize`: from `raw_session.info.tokens`, also read `reasoning` and
  `cache.{read, write}`.
- `abench/trace_model.py` `Trace`: add trace-level `tokens_reasoning`, `cache_read`,
  `cache_write` (`int | None`, default None).
- `abench/metrics.py` `extract`:
  - emit `tokens_reasoning`, `cache_read`, `cache_write`.
  - new **`n_tests_executed`** — the actual number of individual tests the AGENT ran (not
    just invocation count): for each TOOL_CALL in `shell_tool_names` whose command matches
    a `test_command_patterns`, find its paired TOOL_RESULT (by `tool_call_id`) and run
    `verify._parser_for(<first token of command>)` on the result `output`; on success add
    `passed + failed`. Sum across invocations. Unparseable output contributes 0
    (documented). Keep `n_test_runs` (invocation count) — both are distinct, useful signals
    ("ran the test command 3×" vs "exercised 142 tests").
- `abench/report.py` `NUMERIC`: add `tokens_reasoning`, `cache_read`, `cache_write`,
  `n_tests_executed` so they aggregate in both the CLI `summary.md` and the
  `/api/runs/{name}/summary` baseline-vs-augmented table. (`tokens_in`/`tokens_out`/`cost`
  are already in `NUMERIC`.)

**Frontend (aggregate comparison + tooltips):**
- `MetricsJson`/`ConditionSummary` types: add the new keys.
- `SUMMARY_METRICS` descriptor: replace `lowerIsBetter: bool` with
  `direction: "lower" | "higher" | "neutral"`; `SummaryTable` colors the Δ green/red only
  for `lower`/`higher`, and shows `neutral` deltas uncolored. Add rows:
  - `tokens_in` ("tokens read", lower=better), `tokens_out` ("tokens generated",
    lower=better), `tokens_reasoning` ("reasoning tokens", lower) — so "how much more/less
    the LLM read vs generated" is explicit.
  - `n_tests_executed` ("tests executed", **neutral** — more isn't inherently better).
  - `cache_read` ("tokens from prompt cache", **neutral** — informational), `cache_write`
    (neutral). Tooltip: "Served from the provider's prompt cache. With run isolation
    (nonce prefix) ON, expect ≈0 — that's intended, so conditions compare fairly."
  - `cost` ("$ at the provider's rates, from opencode", lower=better). No price table —
    `info.cost` is opencode's authoritative per-run figure; the token breakdown explains
    any delta.
- **Every aggregate/header metric gets a one-line tooltip** of what it means, e.g.
  `steps`: "distinct model steps (turns) in the ReAct chain — one LLM round-trip each
  (reasoning + tool calls or final text). Fewer for the same outcome = more efficient."
  `test runs`: "how many times the agent invoked a test command." `tests executed`: "how
  many individual tests those runs actually exercised (parsed from output)."
- TraceView per-run header also shows tokens in/out/reasoning + cache read/write + cost
  with the same labels/tooltips.

### Live Run page

Replace the broken raw grouping with `turnsFromRawEvents` (same `UiTurn` model) so the
live stream shows correct tool names/results/edits. Live aggregate counts derive from the
normalized stream. "Show raw" keeps the unmodified JSON for debugging.

### Tests (C)

Drive frontend tests with the REAL shape mirrored from
`tests/fixtures/opencode/events_sample.jsonl`: assert a `tool` part renders name/args/
output/exit; a `patch` part renders as a file edit; per-turn tool breakdown is non-zero;
`turnsFromTrace` and `turnsFromRawEvents` produce equivalent `UiTurn`s for the same
session. Backend stays unchanged here (already correct) — but add one cross-check test
asserting `trace.json` `steps`/`turns` round-trip the fixture as the frontend expects.

---

# Part 2 — Verify build/test correctness + configurability (workstream B-core)

## Smarter, ambiguity-aware detection (`abench/verify.py`)

Replace the first-match `detect_command` with explicit detection:

```
def detect_build_systems(workdir) -> list[str]   # subset of ["gradle","maven","pytest"], order = confidence
```
- Gradle markers: `build.gradle`, `build.gradle.kts`, `settings.gradle`, `settings.gradle.kts`, `gradlew`.
- Maven markers: `pom.xml`, `mvnw`.
- pytest markers: `pyproject.toml` + a `tests/` dir (unchanged).

`detect_command(workdir)` returns `(command: str | None, system: str | None,
ambiguous: bool, candidates: list[str])`:
- exactly one system → that system's command (wrapper-aware: `./gradlew test` if
  `gradlew` present else `gradle test`; `./mvnw test` else `mvn test`; `pytest`).
- **both Maven and Gradle present → `ambiguous=True`, `candidates=["gradle","maven"]`,
  and the auto `command` prefers Gradle** (wrapper-aware) — a stray root `pom.xml` in a
  Gradle repo is the common real case (picocli), so Gradle is the better default, and the
  ambiguity flag makes the UI surface it loudly. (Maintains: if `gradlew`/`settings.gradle`
  present, definitely Gradle.)
- none → `(None, None, False, [])`.

`run_verify` and the runner are unchanged in mechanics; they just receive the better
auto command. An explicit `verify.command` always wins (override).

> NOTE: `detect_command` currently returns `str | None` and is called in
> `runner._detect_verify`, `reverify`, and the `/verify_command` endpoint. Change its
> return type to the tuple and update those 3 call sites (they take `.command`); OR keep
> `detect_command(workdir) -> str | None` and add a separate `detect_verify(workdir) ->
> DetectResult` used by the endpoint/UI. **Chosen:** add `detect_verify(workdir)` (rich)
> and reimplement `detect_command` as `detect_verify(workdir).command` — minimal call-site churn, rich data where needed.

## Surface detection + ambiguity + override in the UI (verify fields only)

- Extend `GET /api/experiments/{name}/verify_command` →
  `{command, system, ambiguous, candidates}`.
- The **experiment form's verify section** gets a focused, human treatment (a small custom
  fieldset / uiSchema for `verify.*`, NOT the full form rework):
  - `verify.command` as a plain text field with placeholder = the auto-detected command,
    help text "Leave blank to auto-detect (`<detected>`). Override for a custom build/test
    command, e.g. `./gradlew test`, `mvn -q test`, `pytest -q`."
  - A read-out: "Detected: Gradle · `./gradlew test`" or, when `ambiguous`, a warning:
    "⚠ Both Gradle and Maven detected — using `./gradlew test`. Set the command explicitly
    if that's wrong." (also shown on the ExperimentEdit Fixtures panel, replacing the
    Phase-1 read-only line).
  - `verify.enabled` (checkbox) + `verify.timeout_s` (number) with help.
- This makes verify controllable and fixes the "can't choose build system" complaint.

## Verify results display

Already present (VerifyCard: status/reason/message/counts/failed names/log viewer;
re-verify to populate). With detection fixed, picocli now builds with Gradle → real
pass/fail counts appear. Ensure the trace aggregate header + VerifyCard show
passed/failed/total prominently. No new mechanism needed.

## Tests (B-core)

- `detect_verify` unit tests on synthetic layouts: gradle-only → gradle (wrapper-aware);
  maven-only → maven; **both present (+ gradlew) → gradle, ambiguous=True, candidates**;
  pytest; none. picocli-like layout (`build.gradle`+`settings.gradle`+`gradlew`+`pom.xml`)
  → `./gradlew test`, ambiguous.
- `detect_command` back-compat (returns the tuple's command).
- Endpoint test: `/verify_command` returns `{command, system, ambiguous, candidates}`.
- Frontend: verify section renders the detected command + ambiguity warning + override
  field; saving an override persists `verify.command`.

---

# Part 3 — Real end-to-end verification (the user's "прям проверь")

The dev machine has `gradle`, `mvn`, `java`, `python3`. The implementation MUST include a
real build smoke (an integration test, marked to skip if a tool is absent so CI stays
green elsewhere):

- **Gradle fixture:** a minimal `build.gradle` + one JUnit test → `detect_verify` picks
  `./gradlew test`/`gradle test`, `run_verify` runs it and parses pass/fail correctly.
- **Maven fixture:** a minimal `pom.xml` + one test → picks Maven, runs, parses.
- **Ambiguous (picocli-like):** `build.gradle`+`gradlew`+`pom.xml` → detect picks Gradle
  (`ambiguous=True`); a `mvn test` here would error, so this proves the fix prevents the
  picocli failure.
- **Override:** setting `verify.command` explicitly is honored over detection.
- A `reverify_run` smoke against a real reconstructed Gradle build (end-to-end: patch
  applies → `./gradlew test` → parsed result written back).

(If a real Gradle/Maven build is too slow/heavy for the unit suite, gate these behind a
marker and run them once manually during implementation, capturing the output in the
task report — but detection + parser tests stay in the always-on suite.)

## Risks / notes

- Changing `detect_command`'s contract touches `runner`, `reverify`, and the endpoint —
  the `detect_verify` + thin `detect_command` shim keeps churn minimal.
- The live normalizer duplicates a little of the backend's mapping (unavoidable mid-run);
  it's covered by a test using the real fixture so it can't silently drift.
- Real Gradle/Maven builds need network on first run (dependency download) and are slow;
  gate the heavy integration smokes behind a skip-if-absent / marker.
- Frontend renders finished traces from `trace.steps` — old `trace.json` files written
  before `steps` was serialized still have it (the runner always wrote `to_dict()` incl.
  steps), so existing runs render correctly.
