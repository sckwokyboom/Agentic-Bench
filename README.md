# Agentic-Bench

> A Python harness for measuring how useful graph-slice RAG augmentations are for agentic development.

## Why

Runs an AI agent (OpenCode) on the same task in a chosen project under two conditions (`baseline` and `augmented` — with extra graph context supplied by your RAG system), captures the full agent trace (the ReAct chain: reasoning, tool/command calls, file edits) and computes metrics: does the slice shorten the chain, reduce code exploration, cut the number of test runs, and shrink wall-clock time — without sacrificing correctness?

Correctness is currently manual (the harness saves the final diff; the verdict is yours), while process metrics are extracted from the trace automatically.

## Quick start — the `picocli WordCount` example

A self-contained example lives in [`examples/picocli-wordcount/`](examples/picocli-wordcount/) — a tiny maven + picocli + JUnit project where the body of `countWords(String text)` has been removed and the harness asks the agent to restore it.

```bash
git clone https://github.com/sckwokyboom/Agentic-Bench.git
cd Agentic-Bench
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# opencode 1.15.x — install it if you don't have it yet:
npm i -g opencode-ai

# (optional) wire up a DeepSeek API key:
#   opencode providers login          # pick DeepSeek, paste the key
# then in experiment.yaml:
#   model: deepseek/deepseek-chat
# (by default the example uses opencode/deepseek-v4-flash-free — free, no key required)

abench run examples/picocli-wordcount/experiment.yaml
# results: examples/picocli-wordcount/runs/picocli-countwords/summary.md
```

The full step-by-step README with every metric explained — [`examples/picocli-wordcount/README.md`](examples/picocli-wordcount/README.md).

## Architecture

Two isolation seams:

1. **OpenCode adapter** (`abench/opencode_client.py`) — the only module that knows about opencode's specifics. Drives `opencode run --format json` as a subprocess, reads the JSONL event stream live, then runs `opencode export <id>` for the final persisted session, and emits a normalized `Trace`.
2. **Normalized trace** (`abench/trace_model.py`) — `Step` / `StepKind` / `Trace` are neutral; `metrics.extract` / `report` operate only on them → analysis stays language- and provider-agnostic.

Pipeline of a single run:

```
fixture (copy + git init + one commit, .git stripped)
  → user prompt (task ± augmentation)
  → opencode run → JSONL events (live) + opencode export (canonical)
  → normalize() → Trace
  → metrics.extract(trace, diff) → metrics.json + changes.patch + manifest.json
```

Full details — [`docs/superpowers/specs/2026-05-27-agentic-bench-design.md`](docs/superpowers/specs/2026-05-27-agentic-bench-design.md).

## Repository map

```
abench/                            # Python package
  config.py                        # YAML experiment → typed models (pydantic)
  fixture.py                       # fixture copy + git init + diff + cleanup
  prompt.py                        # compose(task, augmentation)
  opencode_client.py               # RealOpenCodeClient (subprocess + JSONL + export)
  trace_normalize.py               # raw events + session → normalized Trace
  trace_model.py                   # Step / StepKind / Trace
  diffstat.py                      # parse_diffstat(patch) → (files, +, −)
  metrics.py                       # extract(trace, patch, cfg) → metrics dict
  runner.py                        # condition × repetition loop + artefacts
  report.py                        # pandas aggregation → summary.csv + summary.md
  cli.py                           # abench run / abench report
tests/                             # 21 tests, including two e2e against real opencode
examples/picocli-wordcount/        # ready-to-go end-to-end example (synthetic mini-project)
examples/real-codebase/            # "bring your own codebase" recipe (worked through on picocli)
experiments/                       # active experiments (definitions tracked, heavy copies are .gitignored)
  picocli-putValue/                #   ↳ skeleton for picocli/putValue — you clone picocli into ./original and ./stripped
docs/superpowers/
  specs/                           # design spec
  plans/                           # implementation plan
  notes/opencode-api.md            # verified OpenCode API (after the Phase 2 spike)
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
| `success` | `null` — you fill it in manually after comparing against `reference_path` |

`summary.md` aggregates mean/median/std per condition (excluding runs with `interrupted_reason != null`) and shows the `augmented vs baseline` delta in percent. Negative deltas on `n_steps`, `n_reads`, `n_searches`, `n_test_runs`, `duration_s` are the RAG effect you are looking for.

## Tests

```bash
.venv/bin/pytest -q              # 21 passed
```

Two integration tests (`tests/test_opencode_client_integration.py`, `tests/test_run_e2e.py`) drive a **real** opencode against the free model and auto-skip when `opencode` is not on `PATH`.

## Documentation

- Design spec: [`docs/superpowers/specs/2026-05-27-agentic-bench-design.md`](docs/superpowers/specs/2026-05-27-agentic-bench-design.md)
- Implementation plan: [`docs/superpowers/plans/2026-05-27-agentic-bench.md`](docs/superpowers/plans/2026-05-27-agentic-bench.md)
- Notes on the real OpenCode API: [`docs/superpowers/notes/opencode-api.md`](docs/superpowers/notes/opencode-api.md)
- Walk-through of the synthetic example and metrics: [`examples/picocli-wordcount/README.md`](examples/picocli-wordcount/README.md)
- Recipe for a full project (`picocli` + stripped `putValue`): [`examples/real-codebase/README.md`](examples/real-codebase/README.md)
- Convention for the `experiments/` directory and the picocli skeleton: [`experiments/README.md`](experiments/README.md)
