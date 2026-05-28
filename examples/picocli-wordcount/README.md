# Picocli `WordCount` — end-to-end example

A small self-contained Maven + picocli + JUnit project where the body of
the helper method `countWords(String text)` has been removed. We run
`abench` to ask the agent to restore it under two conditions, collect
traces, and compare metrics.

## Layout

```
examples/picocli-wordcount/
  experiment.yaml                       # the experiment config (run this with abench)
  prompts/
    task.md                             # what the agent must do
    system.md                           # fixed system prompt (same for both conditions)
  slices/
    countwords-graph-slice.md           # the toy "RAG slice" used in the augmented condition
  fixtures/
    wordcount-original/                 # ground truth (the agent never sees this)
      pom.xml
      src/main/java/example/WordCount.java        # method body intact
      src/test/java/example/WordCountTest.java
    wordcount-stripped/                 # the working copy the agent runs against
      pom.xml
      src/main/java/example/WordCount.java        # method body replaced with throw
      src/test/java/example/WordCountTest.java
```

Each run copies `wordcount-stripped/` into a fresh temp workdir, strips
any `.git`, creates a single-commit local git repo, then drives
`opencode` against it. The diff against that single commit is recorded as
`changes.patch`.

## 1. Prerequisites (one-time)

- `opencode` installed (you already have 1.15.11).
- `abench` venv active:
  ```
  cd /Users/sckwoky/Projects/Agentic-Bench
  source .venv/bin/activate
  ```
- (Optional) JDK 17+ and Maven on `PATH`. With them the agent can
  actually run `mvn test` inside its ReAct loop; without them, it will
  still attempt commands — `n_test_runs` counts the attempts either way,
  which is the metric we care about.

## 2. Pick a model

The bundled `experiment.yaml` defaults to `opencode/deepseek-v4-flash-free`
(no extra credentials needed; verified working in this repo's
integration test). To switch to the official **DeepSeek API**:

```
opencode providers login          # pick DeepSeek, paste your API key
```

Then edit `experiment.yaml`:
```yaml
model: deepseek/deepseek-chat
```

Or route DeepSeek via OpenRouter (paid, cheap):
```yaml
model: openrouter/deepseek/deepseek-chat-v3.1
```

> Note: `abench` pins `small_model` (used by opencode for title
> generation) to `opencode/mimo-v2.5-free` so background calls never
> bill your DeepSeek account. The pin lives in
> `abench/opencode_client.py` (`_SMALL_MODEL_FREE`).

## 3. Run the experiment

```
abench run examples/picocli-wordcount/experiment.yaml
```

You will see per-run progress on stdout (`abench` streams opencode's
live events to `events.jsonl` and a summary line per condition). Total
time for the default `repetitions: 2` × 2 conditions = ~3–5 minutes on a
free model.

## 4. Where the results land

```
examples/picocli-wordcount/runs/picocli-countwords/
  experiment.resolved.yaml            # snapshot of resolved config (reproducibility)
  baseline/
    rep_0/{events.jsonl, trace.json, changes.patch, metrics.json, manifest.json}
    rep_1/...
  augmented/
    rep_0/...
    rep_1/...
  summary.csv                          # one row per run
  summary.md                           # per-condition mean + delta% (baseline vs augmented)
```

To rebuild just the summary after editing run dirs by hand:
```
abench report examples/picocli-wordcount/runs/picocli-countwords
```

## 5. Reading the metrics

`metrics.json` for each run has, among others:

| Key | What it measures |
|---|---|
| `duration_s` | wall-clock of the opencode subprocess |
| `n_steps` | distinct assistant turns — your "ReAct chain length" |
| `n_tool_calls` (+ `tool_calls_by_name`) | total tool calls + per-tool breakdown |
| `n_test_runs` | bash calls whose command matches `metrics.test_command_patterns` (here: `mvn`, `mvnw`, `gradle`, `gradlew`, `junit`, `pytest`) |
| `n_reads` / `n_searches` | reads/greps/globs — the "exploration" cost (the central signal for whether RAG augmentation reduces it) |
| `n_files_edited`, `diff_lines_added/removed` | from the final git diff |
| `tokens_in` / `tokens_out` / `cost` | from `opencode export` (aggregated) |
| `time_to_first_edit_s` | from start to the first file-edit step |
| `finished` | did the agent complete on its own (not killed by timeout/error) |
| `interrupted_reason` | `null` \| `timeout` \| `rate_limit` \| `error` |
| `success` | **always `null` here — you fill it in manually** after reviewing the diff |

`summary.md` aggregates these per condition (mean across the valid
repetitions, excluding any run with `interrupted_reason != null`) and
shows the delta of augmented vs baseline as a percentage. Negative
deltas on `n_steps`, `n_reads`, `n_searches`, `duration_s`, and
`n_test_runs` are the wins you are hunting for.

## 6. Judge correctness (the manual step)

For each rep look at `changes.patch` and compare against
`fixtures/wordcount-original/src/main/java/example/WordCount.java`. If
the regenerated body is functionally equivalent (passes the
`WordCountTest` expectations listed in
`slices/countwords-graph-slice.md`), mark `success: true` in the
matching `metrics.json`; otherwise `false`. Re-run
`abench report ...` to recompute the summary with success rates.

## 7. Tinkering

- **More repetitions** for tighter stats: bump `repetitions` in the
  YAML. Free models are rate-limited; runtime grows linearly.
- **Different model**: edit the `model` line and rerun. The
  experiment.resolved.yaml records what was actually used.
- **Different augmentation**: swap `slices/countwords-graph-slice.md`
  for a different slice (e.g. omit the idiomatic-shape section to see
  whether the hint matters). Add a third condition with that slice in
  `experiment.yaml`.
- **Different target method**: drop in your own stripped Java file under
  `fixtures/<name>-stripped/`, keep the matching original under
  `<name>-original/`, change `task_prompt` to point at the right method,
  and rerun. The harness doesn't care which Java method is being
  restored — it's all just text diff + tool-call counting on its side.
