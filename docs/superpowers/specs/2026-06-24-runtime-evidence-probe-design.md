# Runtime Evidence Probe — diff-aware runtime diagnostic for the phased agent

Date: 2026-06-24
Status: design approved (brainstorming) — exploratory research + tooling spike

## Framing (what this is, and is NOT)

This is **exploratory: a capability test of our instrumentation + a research probe**, not
a production feature. It answers two distinct questions:

1. **Capability / tooling:** can we cheaply capture *readable, real* runtime evidence
   (the actual call corridor from a test into an edited method, plus the argument
   values it received) **inside the bench loop**, for a single target method?
2. **Research:** does **auto-pushing a tight, ranked diagnostic card** into the phased
   DIAGNOSE loop help the weak model (devstral2-24B) — fewer wasted file reads / tool
   calls, fewer diagnose rounds, faster convergence, ≥ pass rate — vs `phased` /
   `phased_graph`?

Honest bound: if it shows no signal, the conclusion is "*this* evidence form, auto-pushed,
didn't help on these tasks" — **not** "runtime feedback is useless".

## Central abstraction: diff-aware evidence retrieval

NOT "a Java agent that reacts to every diff". The diff reaction already lives in the
orchestrator: the phased DIAGNOSE loop is `edit → run suite → (today) cluster failures`.
We replace the terse clusters with a **diagnostic card** built from layered evidence
sources. The Java agent is just one *evidence source*, not the controller.

Evidence sources, by cost:
- **JUnit XML** (free): failing tests, exception/message, expected/actual (when parseable).
- **Offline `.impact`** (free, **static**): reached-by counts (method → tests). Flagged
  "static, not re-measured this run".
- **Selective runtime probe** (the novel part): the actual stack-at-entry + argument
  values at the **target method only**, captured during the suite run.

## Components (each a unit with one job)

1. **Runtime probe** — a small Byte Buddy Java agent. Instruments **only the target
   method(s)** (passed as agent args, e.g. `…=picocli.CommandLine$Help$TextTable.putValue`).
   On each call: capture (a) the stack snapshot **at entry** (`Thread.currentThread()
   .getStackTrace()` — the target IS on the stack at that instant, so the `test → … →
   target` corridor is real even for assertion bugs), (b) safe-summarized args, (c) on
   exit, a return/throw summary. Appends one JSON line per call to a capture file in the
   workdir (e.g. `.impact/runtime-capture.jsonl`).
   - One probe on the method → captures **every call from every test** in one suite run.
     There is **no per-test setup**. Capture is cheap (one method); volume is handled by
     ranking, not by instrumenting less.

2. **Safe value summarizer** — primitives as-is; strings capped (length + ellipsis);
   collections/arrays as `size + first N`; other objects as `ClassName#identityHash` +
   a few selected/whitelisted fields. **No `toString()`** (side-effect/cost risk), **no
   deep traversal**, **no holding object references** (mutable — summarize at capture time).

3. **Evidence retrieval + ranker** (host side) — reads capture file + JUnit XML + current
   diff + offline `.impact`. **Dedup** capture events by `(failing test, distinct
   call-path, distinct arg-shape)`. Heuristic score (no LLM): `failing_test_relevance +
   call_path_proximity + exception_relevance + novelty − staleness − token_cost`. Cap to
   **top-k** (e.g. ≤5 failing corridors + 1–2 passing for contrast).

4. **Card builder** — renders the ranked evidence into a **≤15-line** card with
   **provenance per block** and **honest relation marking**
   (`direct_stack_hit | static_coverage | no_direct_evidence`). **Evidence, not a fix**:
   at most a "suspicion / check", never "fix by doing X" (else the ablation measures the
   quality of our hint, not the value of the evidence).

5. **Orchestrator integration** — in `orchestrator.run`'s DIAGNOSE loop: after the round's
   suite run, build the card and **auto-push it into the next diagnose prompt** (in place
   of / alongside the cluster list). New condition **`phased-runtime`** (mode
   `phased_runtime`). Record a CONTROLLER event describing what was injected — **excluded
   from comparison metrics** (`n_steps` etc.), exactly like the `phased_graph` events.

## Data flow (one diagnose round, `phased_runtime`)

```
agent edits (implement/diagnose phase)
  → controller runs the suite WITH the probe agent attached
      (gradle test --continue --init-script agent-init.gradle, agent target = exp.target_methods)
  → .impact/runtime-capture.jsonl  +  JUnit XML
  → retrieval + dedup + rank (host)
  → diagnostic card (≤15 lines, provenance, suspicion-not-fix)
  → injected into the next DIAGNOSE prompt
```

Probe injection mechanism (to verify in the spike): a gradle **init script**
(`--init-script`) that adds `-javaagent:<agent.jar>=<targets>` to every `Test` task's
`jvmArgs` — no per-project `build.gradle` edit. The agent jar + init script are baked into
the sandbox image (like `impact_cli`) or mounted via the overlay.

## The card — concrete `putValue` example

```
DIAGNOSTIC CARD · round N · src: runtime probe + JUnit XML + diff + offline .impact

Changed method (this diff):
  Help$TextTable.putValue(int row, int col, Text value)

Top failing corridors (ranked; 3 of 84 failing):
  TextTableTest.testWrap                                 [relation: DIRECT stack hit]
    corridor:  testWrap → Help.layout → TextTable.addRowValues:88 → putValue:42
    runtime:   putValue(row=0, col=1, value=Text("a long line…", len=37)); colWidth=20
               effect: wrote 37 chars, no wrap inserted
    expected/actual (parsed): "a long\n  line…"  vs  "a long line…"
    code: putValue:42  `column.text = value;`   ← edited line

Offline impact (static, NOT re-measured this run):
  putValue covered by ~412 tests; 84 currently failing are within that set.

Suspicion (check, not fix):
  wrap not applied when value length exceeds column width on this path.
```

For assertion bugs where the target is genuinely absent from the stack, the corridor block
is marked `relation: no_direct_evidence` rather than inventing a static path.

## Invariants (ablation validity)

- **Public tests only** — the agent can already run these, so this is just better
  observability, not oracle leakage. No hidden-test / expected-behavior injection.
- **Evidence, not solutions** — no patch advice; "suspicion / check" only.
- **Honest provenance** — every block flags its source; offline data flagged static /
  not re-measured; `relation` flag never claims a path that wasn't observed.
- **Trace-comparable, metric-neutral** — injected cards are CONTROLLER events, excluded
  from `n_steps` / tool counts so the cross-condition comparison stays clean.

## Phasing / de-risk

1. **Vertical-slice spike (first deliverable, ~½–1 day):** instrument **only** `putValue`,
   run **one** failing test under the agent, dump `(stack-at-entry + arg summary)`.
   Proves: the snapshot is readable, the corridor is real, and `-javaagent` injection works
   in the docker sandbox + gradle test JVM. **Go/no-go gate.**
2. **If go:** build the summarizer + retrieval/ranker + card builder + diagnose
   integration → ship the `phased-runtime` condition; compare by trace vs
   `phased` / `phased_graph`.
3. **Out of scope (future, separate specs):** the cheap no-instrumentation baseline card
   (S1, JUnit+graph only) as a contrast; structured session-state memory with provenance
   (S3); learned ranker; the push-vs-pull ablation axis (`explain_failures()` tool);
   instrumenting top-k callers/callees beyond the target method.

## Risks / unknowns (to resolve, mostly in the spike)

- **`-javaagent` injection** into the forked gradle Test JVM inside the sandbox — the
  init-script approach is the plan; verify it reaches the test JVM (not just the daemon).
- **Sandbox file IO / ownership** — the capture file is written by the container (root);
  the host reads it. Reuse the best-effort ownership/`clean` patterns already added for the
  phased loop.
- **Summarizer safety** — no `toString`, no deep dump, no held references.
- **Upward path (target → assert) is data-flow, not call-flow** — not mechanically traced;
  the card gives call-path + values + expected/actual and lets the LLM connect them.
- **Volume** — capture-all-then-rank; the cap is mandatory, not optional (putValue: ~412
  covering tests × many calls/test → thousands of events).
- **Staleness** — mitigated by design: phased re-runs the suite each round, so capture is
  always post-current-diff (no stale cross-round caching).

## Success criteria

- **Capability:** the probe reliably produces a readable, real `(corridor + args)` capture
  for the target in the sandbox (spike passes).
- **Research:** on the same tasks, `phased-runtime` vs `phased` / `phased_graph` shows ≥1
  of: fewer file reads, fewer tool calls, fewer diagnose rounds (accepted+reverted),
  faster convergence, ≥ pass rate — at acceptable token cost. Compared **by trace** +
  existing metrics (`n_reads`, `n_tool_calls`, `controller_test_runs`, rounds,
  `tests_pass_rate`, tokens).
