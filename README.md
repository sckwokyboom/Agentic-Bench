# Agentic-Bench

> A Python harness + web UI for measuring how useful graph-slice RAG augmentations are for agentic development.

## Why

Runs an AI agent (OpenCode) on the same task in a chosen project under two conditions (`baseline` and `augmented` — with extra graph context supplied by your RAG system), captures the full agent trace (the ReAct chain: reasoning, tool/command calls, file edits) and computes metrics: does the slice shorten the chain, reduce code exploration, cut the number of test runs, and shrink wall-clock time — without sacrificing correctness?

Correctness is verified automatically: after each run the harness detects the project's build tool (`mvn` / `gradle` / `pytest` / `cargo` / …), runs the test suite against the agent's edits, and records pass/fail (you can still override the verdict by hand). Process metrics are extracted from the trace automatically.

## Quick start — the picocli `putValue` example (real project)

The main worked example restores **one method** — `putValue(...)` — in the **full, real [picocli](https://github.com/remkop/picocli) codebase**. Only that method's body is stripped; the signature, Javadoc, every test, and the rest of the ~80 MB project stay intact as shared context. The agent has to reconstruct the body from that context (and, in the `augmented` condition, from your graph slice).

Every step below runs from a clean machine. Commands are from the repo root unless noted.

### 1. Install the harness

```bash
git clone https://github.com/sckwokyboom/Agentic-Bench.git
cd Agentic-Bench
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# opencode 1.15.x — install if you don't have it:
npm i -g opencode-ai
opencode --version

abench --help
```

The example defaults to `opencode/deepseek-v4-flash-free` (free, no key). To use a paid model, run `opencode providers login` (pick DeepSeek, paste the key) and set `model: deepseek/deepseek-chat` in the experiment's `experiment.yaml`.

### 2. Populate the fixtures

The experiment ships its config, prompts, and a slice placeholder under git; you provide the two code trees, which are git-ignored (`experiments/*/original/`, `experiments/*/stripped/`):

```bash
cd experiments/picocli-putValue
git clone https://github.com/remkop/picocli.git original
cp -R original stripped
```

- `original/` is the **reference** (`reference_path`) — the intact project, used for comparison.
- `stripped/` is the **fixture** (`fixture_path`) — what the agent works on, copied fresh per run.

### 3. Strip the target method body in `stripped/`

Open `stripped/src/main/java/picocli/CommandLine.java`, find `putValue(...)`, and replace **only its body** with:

```java
throw new UnsupportedOperationException("TODO: implement putValue");
```

Leave the signature, Javadoc, annotations, and every other file untouched — that's the context shared by both conditions. The original body now lives only in `original/`. (The task prompt that the agent sees is in [`experiments/picocli-putValue/prompts/task.md`](experiments/picocli-putValue/prompts/task.md).)

### 4. (optional) Drop in a real graph slice

`slices/putValue-graph-slice.md` is a placeholder. For a real comparison, your RAG/graph system writes the slice for the `augmented` condition here; for a manual smoke run, hand-write a hint modelled on [`examples/picocli-wordcount/slices/countwords-graph-slice.md`](examples/picocli-wordcount/slices/countwords-graph-slice.md).

### 5. Run and read the results

```bash
cd ../..          # back to repo root, venv still active
abench run experiments/picocli-putValue/experiment.yaml
```

This executes 2 conditions × 3 repetitions and writes the artefacts below. If the project's build tool is on `PATH` (for picocli: **Maven + a JDK**, plus network for the first dependency download), each rep is auto-verified against picocli's test suite and `success` is filled in automatically; otherwise `verify_status` is `skipped`/`error` and you set `success` by hand. Artefacts:

```
experiments/picocli-putValue/runs/picocli-putValue/
  summary.md                              # ← start here
  summary.csv
  baseline/rep_{0,1,2}/{events.jsonl, trace.json, changes.patch, metrics.json, manifest.json}
  augmented/rep_{0,1,2}/...
```

`summary.md` is the baseline vs augmented table with deltas on `n_steps`, `n_reads`, `n_searches`, `n_test_runs`, `duration_s`, `time_to_first_edit_s`. Negative deltas there are the RAG effect you are looking for. Re-aggregate any time (e.g. after a manual `success` edit in a `metrics.json`):

```bash
abench report experiments/picocli-putValue/runs/picocli-putValue
```

Full walk-through (choosing a target, stripping precisely, reading every metric, pitfalls) — [`experiments/picocli-putValue/README.md`](experiments/picocli-putValue/README.md).

> **Want a 5-second synthetic smoke first?** [`examples/picocli-wordcount/`](examples/picocli-wordcount/) is a tiny self-contained maven + picocli + JUnit project (no external clone needed):
> ```bash
> abench run examples/picocli-wordcount/experiment.yaml
> ```

## Web UI

Browse experiments, edit them in a schema-driven form, launch runs with a live ReAct stream, and inspect finished traces — all in the browser, served by one local process.

Build the frontend bundle once (Node 18+):

```bash
cd web && npm install && npm run build && cd ..
```

Start the server (serves the REST/WebSocket API **and** the built UI on a single port — no CORS, no second process):

```bash
abench-ui --experiments-dir experiments
# → open http://127.0.0.1:8765
```

What you get:

- **Experiments** — list / + New / ↑ Upload YAML / Run / Edit / Delete, with a per-experiment status pill.
- **Edit** — a form generated live from the pydantic schema (`/api/schema`): per-field validation, a live model-availability check with an "Add API key" dialog, `target_methods` chip editor, and sticky panels for validation errors, the run plan, fixture presence, and previous runs. Invalid YAML physically cannot be saved.
- **Run** — the live ReAct stream grouped turn-by-turn, a progress header, a per-rep sidebar with verify chips, and Cancel. Reconnects and replays if the socket drops.
- **Trace** — verdict banner, aggregate stats, a turn-by-turn timeline (one card per model message, with "show raw"), the verify card, the final diff, an optional method comparison (`original` vs the agent's regeneration), a metrics drawer, and prev/next-rep navigation.

`abench-ui` refuses to start if the bundle is missing — build it first, or pass `--skip-bundle-check` for an API-only boot. Other flags: `--host`, `--port` (default `8765`), `--experiments-dir` (default `experiments`).

**Frontend dev mode** (hot reload; Vite proxies `/api` + `/ws` to the backend):

```bash
# terminal 1
abench-ui --experiments-dir experiments --skip-bundle-check
# terminal 2
cd web && npm run dev          # → http://127.0.0.1:5173
```

## Architecture

Isolation seams:

1. **OpenCode adapter** (`abench/opencode_client.py`) — the only module that knows opencode's specifics. Drives `opencode run --format json` as a subprocess, reads the JSONL event stream live, then runs `opencode export <id>` for the final persisted session, and emits a normalized `Trace`.
2. **Normalized trace** (`abench/trace_model.py`) — `Step` / `StepKind` / `Trace` are neutral; `metrics.extract` / `report` operate only on them → analysis stays language- and provider-agnostic.
3. **Verify subsystem** (`abench/verify.py` + `abench/verify_parsers.py`) — auto-detects the build tool, runs the project test suite against the agent's edits, parses pass/fail counts.
4. **Web layer** (`abench_ui/` FastAPI + `web/` React) — calls `run_experiment(...)` **in-process** and mirrors each raw opencode event onto a WebSocket; the pydantic `Experiment` model is the single source of truth for both the form schema and validation.

Pipeline of a single run:

```
fixture (copy + git init + one commit, .git stripped)
  → user prompt (task ± augmentation)
  → opencode run → JSONL events (live) + opencode export (canonical)
  → normalize() → Trace
  → verify (auto-detect build tool, run test suite) → verify_status + counts
  → metrics.extract(trace, diff) → metrics.json + changes.patch + manifest.json
```

Full details — [`docs/superpowers/specs/2026-05-27-agentic-bench-design.md`](docs/superpowers/specs/2026-05-27-agentic-bench-design.md) (harness) and [`docs/superpowers/specs/2026-05-29-web-ui-design.md`](docs/superpowers/specs/2026-05-29-web-ui-design.md) (web UI).

## Repository map

```
abench/                            # Python harness
  config.py                        # YAML experiment → typed models (pydantic) + verify/isolation/target_* fields
  fixture.py                       # fixture copy + git init + diff + cleanup
  prompt.py                        # compose(task, augmentation)
  opencode_client.py               # RealOpenCodeClient (subprocess + JSONL + export)
  trace_normalize.py               # raw events + session → normalized Trace (+ per-turn info)
  trace_model.py                   # Step / StepKind / Trace / TurnInfo / verify_* / final_diff_summary
  verify.py, verify_parsers.py     # auto-detect build tool + run test suite + parse results
  diffstat.py                      # parse_diffstat(patch) → (files, +, −)
  metrics.py                       # extract(trace, patch, cfg) → metrics dict (success auto from verify)
  runner.py                        # condition × repetition loop + post-rep verify + artefacts
  report.py                        # pandas aggregation → summary.csv + summary.md
  cli.py                           # abench run / abench report

abench_ui/                         # FastAPI app (REST + WebSocket) + SPA serving
  server.py                        # app factory, routes, WS, static bundle
  schema.py experiments.py runs.py validate.py providers.py
  run_session.py ws_client.py ws_buffer.py
  cli.py                           # abench-ui console-script
  static/                          # built frontend bundle (gitignored; `cd web && npm run build`)

web/                               # React 18 + MUI v5 + Vite frontend (sources)
  src/pages/{ExperimentList,ExperimentEdit,Run,TraceView}.tsx
  src/{api,ws,components,lib,schema}/   tests/

tests/                             # Python tests (harness + web API/WS), incl. e2e against real opencode
examples/picocli-wordcount/        # tiny self-contained end-to-end example (no external clone)
examples/real-codebase/            # "bring your own codebase" recipe (worked through on picocli)
experiments/                       # active experiments (definitions tracked; original/stripped/runs are .gitignored)
  picocli-putValue/                #   ↳ the main example — clone picocli into ./original and ./stripped
docs/superpowers/{specs,plans,notes}/
```

## Metrics

The `metrics.json` of each run contains:

| Key | Meaning |
|---|---|
| `duration_s` | run wall-clock |
| `n_steps` | distinct model steps — length of the ReAct chain |
| `n_tool_calls` (+ `tool_calls_by_name`) | total tool calls + breakdown by name |
| `n_test_runs` | bash commands matching `test_command_patterns` (`pytest`/`mvn`/`gradle`/…) |
| `n_reads` / `n_searches` | read/grep/glob/list — "code exploration volume" |
| `n_files_edited`, `diff_lines_added/removed` | from the git diff against the seed commit |
| `tokens_in/out`, `cost` | from the persisted session (aggregated) |
| `time_to_first_edit_s` | from start to the first edit |
| `finished` | did the agent reach the end on its own |
| `interrupted_reason` | `null` \| `timeout` \| `rate_limit` \| `error` |
| `verify_status` | `passed` \| `failed` \| `skipped` \| `error` \| `timeout` |
| `verify_passed_count` / `verify_failed_count` (+ `verify_failed_names`) | parsed from the test-suite output |
| `verify_command`, `verify_duration_s` | the command run and its wall-clock |
| `success` | auto: `true` if verify passed, `false` if it failed, `null` if skipped/error/timeout (manual override allowed) |

`summary.md` aggregates mean/median/std per condition (excluding runs with `interrupted_reason != null`) and shows the `augmented vs baseline` delta in percent. Negative deltas on `n_steps`, `n_reads`, `n_searches`, `n_test_runs`, `duration_s` are the RAG effect you are looking for.

## Tests

```bash
.venv/bin/pytest -q              # Python: harness + web API/WS (113 passed)
cd web && npm test -- --run      # Frontend: Vitest + Testing Library (47 passed)
```

The Python integration tests (`tests/test_opencode_client_integration.py`, `tests/test_run_e2e.py`) drive a **real** opencode against the free model and auto-skip when `opencode` is not on `PATH`.

## Documentation

- Harness design spec: [`docs/superpowers/specs/2026-05-27-agentic-bench-design.md`](docs/superpowers/specs/2026-05-27-agentic-bench-design.md)
- Web UI design spec: [`docs/superpowers/specs/2026-05-29-web-ui-design.md`](docs/superpowers/specs/2026-05-29-web-ui-design.md)
- Implementation plans: [harness](docs/superpowers/plans/2026-05-27-agentic-bench.md) · [web UI backend](docs/superpowers/plans/2026-05-29-web-ui-backend.md) · [web UI frontend](docs/superpowers/plans/2026-05-29-web-ui-frontend.md)
- Notes on the real OpenCode API: [`docs/superpowers/notes/opencode-api.md`](docs/superpowers/notes/opencode-api.md)
- The main picocli `putValue` example: [`experiments/picocli-putValue/README.md`](experiments/picocli-putValue/README.md)
- Synthetic example & metric walk-through: [`examples/picocli-wordcount/README.md`](examples/picocli-wordcount/README.md)
- "Bring your own codebase" recipe: [`examples/real-codebase/README.md`](examples/real-codebase/README.md)
- The `experiments/` convention: [`experiments/README.md`](experiments/README.md)
