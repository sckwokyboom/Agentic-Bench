# Agentic-Bench

> A Python harness + web UI for measuring how useful graph-slice RAG augmentations are for agentic development.

## Why

Runs an AI agent (OpenCode) on the same task in a chosen project under two conditions (`baseline` and `augmented` — with extra graph context supplied by your RAG system), captures the full agent trace (the ReAct chain: reasoning, tool/command calls, file edits) and computes metrics: does the slice shorten the chain, reduce code exploration, cut the number of test runs, and shrink wall-clock time — without sacrificing correctness?

Correctness is verified automatically: after each run the harness detects the project's build tool (`mvn` / `gradle` / `pytest` / `cargo` / …), runs the test suite against the agent's edits, and records pass/fail (you can still override the verdict by hand). Process metrics are extracted from the trace automatically.

## Quick start — from git clone to a run in the browser

The main worked example restores **one method** — `putValue(...)` — in the **full, real [picocli](https://github.com/remkop/picocli) codebase**, then runs it as an A/B experiment you launch and watch **from the browser UI**. Only that method's body is stripped; the signature, Javadoc, every test, and the rest of the ~80 MB project stay intact as shared context. The agent reconstructs the body from that context (and, in the augmented conditions, from your graph slice or the `impact` tool).

Every step runs from a clean machine, from the repo root unless noted.

**Prerequisites.** Python 3.12+, Node 18+, a **JDK 21** (the single version that satisfies the whole toolchain), **Docker** (or podman), and **opencode 1.15.x**. OS: macOS and Linux run natively; on **Windows 11 use WSL2** and treat it as Linux. Full machine checklist and per-OS notes live in [`experiments/picocli-putValue/REPRODUCE.md`](experiments/picocli-putValue/REPRODUCE.md).

### 1. Clone both repos

The experiment supplies its `impact` tool and graph slices from a sibling **Graph-Tipper** checkout (named Graph-Augmentator on GitHub):

```bash
git clone https://github.com/sckwokyboom/Agentic-Bench.git
git clone https://github.com/sckwokyboom/Graph-Augmentator.git Graph-Tipper
cd Agentic-Bench
```

### 2. Install the harness + opencode

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

npm i -g opencode-ai        # opencode 1.15.x — install if you don't have it
opencode --version          # confirm 1.15.x
abench --help
```

### 3. Build the web bundle (required for the UI)

`abench-ui` refuses to start without the built frontend, so build it once (Node 18+):

```bash
cd web && npm install && npm run build && cd ..
```

### 4. Register Graph-Tipper

`experiment.yaml` mounts `{lib:graph-tipper}` into the sandbox, so point abench at the clone from step 1 (this writes a machine-local, gitignored `.abench.local.json` — no env var to export):

```bash
abench lib add graph-tipper /absolute/path/to/Graph-Tipper
abench lib list
```

### 5. Prepare the fixtures — download picocli + strip `putValue` (scripted)

```bash
export JAVA_HOME=…          # a JDK 21 (macOS: $(/usr/libexec/java_home -v 21))
cd experiments/picocli-putValue
python prepare.py           # clones picocli @ fixture.lock sha, strips putValue's body, regenerates slices
cd ../..
```

This is the **scripted** replacement for any hand-editing. `prepare.py` populates `original/` (the intact **reference**) and `stripped/` (the **fixture**, with `putValue`'s body swapped for a `throw new UnsupportedOperationException(...)` stub via `strip_target.py`), then regenerates the graph slices/overlay. For just the download + strip: `python prepare.py --only fixtures` (the slices + `impact` overlay are already committed). **Run this before step 6** — the sandbox image warms its Gradle cache from `stripped/`, so that directory must exist first. (Manual recipe, if ever needed: [`experiments/picocli-putValue/README.md`](experiments/picocli-putValue/README.md).)

### 6. Machine check + build the sandbox image

```bash
python scripts/setup_check.py --container --build-image
```

Verifies opencode 1.15.x, JDK, git and docker/podman, then builds the `abench-sandbox:latest` image (JDK 21 + Gradle + opencode). Its warm-cache stage `COPY`s `experiments/picocli-putValue/stripped/` (from step 5) and pre-compiles picocli's tests, so **`stripped/` must already exist** — that's why `prepare.py` runs first. Anything missing is printed with how to get it.

### 7. Pick a model

`experiment.yaml` defaults to the direct DeepSeek API — set your key on the host and it is forwarded into the sandbox automatically:

```bash
export DEEPSEEK_API_KEY=sk-...
```

No key? Set `model: opencode/deepseek-v4-flash-free` in the experiment for a free model instead.

### 8. Launch the UI and run it from the browser

```bash
abench-ui --experiments-dir experiments
# → open http://127.0.0.1:8765
```

In the browser: open **picocli-putValue**, hit **Run**, and watch the live ReAct stream turn-by-turn with a per-rep verify chip; when a rep finishes, open **Trace** for the verdict banner, the final diff, the `original`-vs-regenerated method comparison, and the metrics drawer. You can also tweak the experiment (model, conditions, `target_methods`) in the schema-driven **Edit** form first. This runs the full A/B — **9 conditions × 3 repetitions** in the container sandbox — and auto-verifies each rep against picocli's **Gradle** test suite (`./gradlew test`, JDK 21, baked into the image). For a focused run, trim the condition list in the Edit form (e.g. keep only `baseline` + `augmented`).

### Headless alternative (CLI)

Prefer the terminal? Skip step 3 and run the same experiment without the UI:

```bash
abench run experiments/picocli-putValue/experiment.yaml
abench report experiments/picocli-putValue/runs/picocli-putValue   # re-aggregate summary.md / summary.csv
```

Results land under `experiments/picocli-putValue/runs/picocli-putValue/<batch-id>/` — start at `summary.md` (per-condition means and the augmented-vs-baseline deltas on `n_steps`, `n_reads`, `n_searches`, `n_test_runs`, `duration_s`, `time_to_first_edit_s`). Full walk-through — [`experiments/picocli-putValue/README.md`](experiments/picocli-putValue/README.md).

> **Want a 5-second smoke with no Docker, no key, and no external clone?** [`examples/picocli-wordcount/`](examples/picocli-wordcount/) is a tiny self-contained maven + picocli + JUnit project — run `abench run examples/picocli-wordcount/experiment.yaml`, or open it in the UI.

## Web UI

The Quick start above already launches the UI (build the bundle in step 3, start the server in step 8). It serves the REST/WebSocket API **and** the built SPA on a single port — no CORS, no second process. What the screens give you:

- **Experiments** — list / + New / ↑ Upload YAML / Run / Edit / Delete, with a per-experiment status pill.
- **Edit** — a form generated live from the pydantic schema (`/api/schema`): per-field validation, a live model-availability check with an "Add API key" dialog, `target_methods` chip editor, and sticky panels for validation errors, the run plan, fixture presence, and previous runs. Invalid YAML physically cannot be saved.
- **Run** — the live ReAct stream grouped turn-by-turn, a progress header, a per-rep sidebar with verify chips, and Cancel. Reconnects and replays if the socket drops.
- **Trace** — verdict banner, aggregate stats, a turn-by-turn timeline (one card per model message, with "show raw"), the verify card, the final diff, an optional method comparison (`original` vs the agent's regeneration), a metrics drawer, and prev/next-rep navigation.

`abench-ui` refuses to start if the bundle is missing — build it (Quick start step 3), or pass `--skip-bundle-check` for an API-only boot. Other flags: `--host`, `--port` (default `8765`), `--experiments-dir` (default `experiments`).

**Frontend dev mode** (hot reload; Vite proxies `/api` + `/ws` to the backend):

```bash
# terminal 1
abench-ui --experiments-dir experiments --skip-bundle-check
# terminal 2
cd web && npm run dev          # → http://127.0.0.1:5173
```

## Troubleshooting

Common first-run errors on a clean machine (the container + UI path):

- **`Missing local library path(s) in the registry (.abench.local.json): - graph-tipper`** — the Graph-Tipper clone isn't registered. `.abench.local.json` is gitignored, so a fresh clone starts with an empty registry. Fix (Quick start steps 1 + 4):
  ```bash
  git clone https://github.com/sckwokyboom/Graph-Augmentator.git Graph-Tipper
  abench lib add graph-tipper /absolute/path/to/Graph-Tipper
  abench lib list
  ```
- **`setup_check --build-image` / `docker build` fails with `COPY failed: … stripped: no such file or directory`** — the fixtures aren't prepared yet. The image warms its Gradle cache from `experiments/picocli-putValue/stripped/`, which is gitignored (absent in a fresh clone). Run the scripted download + strip first, then rebuild (this is why Quick start puts step 5 before step 6):
  ```bash
  python experiments/picocli-putValue/prepare.py --only fixtures
  python scripts/setup_check.py --container --build-image
  ```
- **The form won't Save/Run and shows `.benchmark -- must be object` (or `.orchestration -- must be object`)** — you're on a stale web bundle. This was a schema-collapse bug for optional nested models (`benchmark`/`orchestration` are unset in a normal fixture experiment, and the form wrongly rejected their `null`). Rebuild the bundle and restart the server:
  ```bash
  cd web && npm run build && cd ..   # then restart abench-ui
  ```
- **`container runtime 'docker' not found` or the sandbox image is missing** — install Docker Desktop (WSL2 backend on Windows) or podman, then build the image:
  ```bash
  python scripts/setup_check.py --container --build-image
  ```
- **Gradle verify fails with a Java version error** — the toolchain needs **JDK 21**. Point `JAVA_HOME` at a 21 (macOS: `export JAVA_HOME=$(/usr/libexec/java_home -v 21)`; Linux/WSL: a `openjdk-21` install dir).
- **Model calls fail / 401** — `experiment.yaml` uses the direct DeepSeek API; `export DEEPSEEK_API_KEY=...` before the run (it's forwarded into the sandbox), or switch `model:` to the free `opencode/deepseek-v4-flash-free`.
- **`unable to get local issuer certificate` during docker build/run** — behind a corporate CA: drop the `*.crt` files into `docker/extra-ca/` and rebuild (`python scripts/setup_check.py --container --build-image`). A good build prints `[extra-ca] registered N cert(s)`.

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
