# OpenCode API — verified notes (Task 11 spike)

Verified against `opencode 1.15.11` (macOS arm64, `npm i -g opencode-ai`), May 2026.
Captured live samples in `tests/fixtures/opencode/` (Mistral run, schema identical for opencode-native models).

## 1. Install & paths

- Install: `npm i -g opencode-ai` (also `brew install sst/tap/opencode` or `curl -fsSL https://opencode.ai/install | bash`).
- `opencode debug paths` (verified):
  - `data` — `~/.local/share/opencode` (SQLite DB, auth, logs)
  - `config` — `~/.config/opencode` (user config)
  - `cache` — `~/.cache/opencode`
  - `state` — `~/.local/state/opencode`
- Storage: **SQLite**, file `~/.local/share/opencode/opencode.db`. Not a JSON-on-disk format.

## 2. Headless run — primary driving mode

```
opencode run --format json --print-logs --log-level INFO \
  --dir <cwd> \
  --model <provider/id> \
  --agent <name> \
  --dangerously-skip-permissions \
  "<user prompt>"
```

- `--format json` → **stdout = JSONL stream** (one event per line). Confirmed by capture; see schema §4.
- `--print-logs --log-level INFO` → **stderr = structured log lines** (live progress, bus events, LLM call lifecycle); see §5.
- `--dir` binds the run to a working directory (the cwd seen by the agent).
- `--model provider/id` overrides config. Format e.g. `openrouter/...`, `mistral/...`, `opencode/...`.
- `--agent <name>` selects an agent (default `build`). Sets system prompt + permissions.
- `--dangerously-skip-permissions` auto-approves tool permission prompts — required for batch use, otherwise the run hangs awaiting interactive approval.
- Other relevant flags: `--session <id>` (continue), `--fork`, `--attach <url>` (attach to running `opencode serve`), `--variant`, `--port`.

## 3. Configuration

User config: `~/.config/opencode/opencode.jsonc` (JSONC). Verified keys (resolved via `opencode debug config`):

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "model": "opencode/deepseek-v4-flash-free",
  "small_model": "opencode/mimo-v2.5-free"
}
```

- `model` — default primary model.
- `small_model` — **critical**: model used for background tasks (title generation, summarization). Default is the paid `anthropic/claude-haiku-4.5`; on accounts with no paid balance this causes a `402` error and aborts the whole run even when the main model is free. Always pin this to a free model alongside the main one.
- The schema URL is fetched by editors but the config tolerates unknown keys.

## 4. stdout JSONL — live event stream

Each line is one JSON event with this envelope:

```json
{ "type": "<event-type>", "timestamp": <ms epoch>, "sessionID": "ses_…", "part": { … } }
```

Observed event types (`type` at envelope level — snake_case):
- `step_start` — assistant step begins (one per model call).
- `tool_use` — a tool invocation completed within the current step (one event per tool call; carries input + output + status).
- `step_finish` — assistant step ends; carries per-step tokens, cost, and `reason` (`"tool-calls"`, `"stop"`, …).
- `text` — assistant text part of a message (the textual reply).

Other types likely emitted (seen in binary literals; confirm if encountered): `reasoning`, `patch`, `snapshot`, plus persisted-only `tool-call` / `tool-result` split forms. The captured sample only triggers `step_start`/`step_finish`/`tool_use`/`text`; an end-of-turn `step_finish` may be omitted when the final part is plain text with no further tool round-trip.

Confirmed on a real 1.15.11 run with a file edit (picocli putValue, 2026-06-10): the `edit` tool produces only a `tool` part — **no `patch` part appears in the run stream**. So normalize's `patch`→`FILE_EDIT` branch never fires there, and `metrics.time_to_first_edit_s` is keyed off edit-named tool calls (`metrics.edit_tool_names`, default `edit`/`write`/`patch`) with FILE_EDIT kept as a secondary source.

Important naming gotcha: **stream event types use snake_case** (`step_start`, `tool_use`) while **`part.type` inside them uses hyphenated form** (`step-start`, `tool`, `text`). The normalizer must handle both.

### Part shapes (verified against Mistral and opencode-native runs)

**`text`** part:
```json
{ "type": "text", "id": "prt_…", "messageID": "msg_…", "sessionID": "ses_…",
  "text": "done", "time": { "start": 1779964688817, "end": 1779964688822 } }
```

**`tool`** part (combined call+result; `state.status` ∈ {`completed`, `error`, possibly `pending`/`running` mid-stream}):
```json
{ "type": "tool", "id": "prt_…", "messageID": "msg_…", "sessionID": "ses_…",
  "callID": "blBHpggrk",
  "tool": "bash",
  "state": {
    "status": "completed",
    "input":  { "command": "ls", "description": "…" },
    "output": "<stdout>",
    "metadata": { "output": "<stdout>", "exit": 0, "description": "…", "truncated": false },
    "title": "…",
    "time": { "start": 1779964688242, "end": 1779964688246 }
  } }
```

**`step-start`** part:
```json
{ "type": "step-start", "id": "prt_…", "messageID": "msg_…", "sessionID": "ses_…" }
```

**`step-finish`** part:
```json
{ "type": "step-finish", "id": "prt_…", "messageID": "msg_…", "sessionID": "ses_…",
  "reason": "tool-calls",
  "tokens": { "total": 7864, "input": 7844, "output": 20, "reasoning": 0,
              "cache": { "write": 0, "read": 0 } },
  "cost": 0.0007904 }
```

### Turn boundaries

A turn = one model call. Each turn shares one `messageID` and is bounded by a `step_start` → … → `step_finish` event cluster. The user message and each assistant message has its own `messageID` (e.g. user `msg_e6db…`, assistant turn 1 `msg_e6e2…a2b4`, assistant turn 2 `msg_e6e2…77c`).

Recommended: **count turns by distinct `messageID` across assistant parts**, equivalently by `step_start` events.

## 5. stderr — log stream (also a live signal)

`--print-logs --log-level INFO` writes one structured log line per event in this format:

```
INFO|ERROR  <ISO-timestamp> +<ms-since-prev>ms service=<svc> [k=v …] [free-text tail]
```

Observed `service` values: `bus`, `config`, `db`, `default`, `file`, `file.watcher`, `format`, `llm`, `lsp`, `plugin`, `project`, `provider`, `server`, `session`, `session.processor`, `session.prompt`, `session.tools`, `shell-tool`, `skill`, `tool.registry`.

`service=bus` lines carry the canonical session event types:
- `session.created`, `session.updated`, `session.deleted`
- `message.updated`, `message.part.updated`
- `session.status` (idle/active)
- `session.diff` (file diff)
- `session.next.agent.switched`, `session.next.model.switched`
- `command.executed`

LLM lifecycle (`service=llm`) lines tell you when a model call starts and what it costs, with `providerID`, `modelID`, `session.id`, `small=<bool>`, `agent`, `mode`.

This is useful for **wall-clock per-step timing** when stdout granularity isn't enough.

## 6. Persisted session export

```
opencode export <sessionID>            # JSON to stdout (use > to save)
opencode export <sessionID> --sanitize # redact sensitive transcript and file data
opencode session list                  # scoped to project of current cwd
```

Schema (verified — full sample at `tests/fixtures/opencode/session_sample.json`):

```jsonc
{
  "info": {
    "id": "ses_…", "slug": "…", "projectID": "global",
    "directory": "/private/tmp/oc-probe", "path": "private/tmp/oc-probe",
    "title": "…", "agent": "build",
    "model": { "id": "…", "providerID": "…", "variant": "default" },
    "version": "1.15.11",
    "summary": { "additions": 0, "deletions": 0, "files": 0 },
    "cost": 0,
    "tokens": { "input": 0, "output": 0, "reasoning": 0,
                "cache": { "read": 0, "write": 0 } },
    "permission": [ … ],
    "time": { "created": <ms>, "updated": <ms> }
  },
  "messages": [
    { "info": { "role": "user" | "assistant",
                "time": { "created": <ms> },
                "agent": "build",
                "model": { "providerID": "…", "modelID": "…" },
                "summary": { "diffs": [ … ] },
                "id": "msg_…", "sessionID": "ses_…" },
      "parts": [ /* same part shapes as in §4 */ ] }
  ]
}
```

Notes:
- `info.summary` mirrors the agent's net file changes (additions/deletions/files).
- `info.tokens` and `info.cost` are **aggregated** over all turns (useful canonical totals).
- `messages[].parts[]` contains the persisted parts — equivalent to what the stdout stream emitted, but in storage form.

## 7. Models verified to work in this environment

- `opencode/deepseek-v4-flash-free` (primary) — opencode-native, free, no third-party rate limits.
- `opencode/mimo-v2.5-free` (small) — opencode-native, free.
- `opencode/nemotron-3-super-free`, `opencode/big-pickle` — also opencode-native (latter likely paid).
- `mistral/devstral-small-2507` and `mistral/ministral-3b-latest` — Mistral free tier; confirmed working.

Models that did **NOT** work on this account at probe time:
- `openrouter/google/gemini-2.0-flash-exp:free` — `404 "No endpoints found"` (model retired from OpenRouter).
- `openrouter/meta-llama/llama-3.3-70b-instruct:free` — 75 consecutive `429`s (OpenRouter free-tier RPM cap with zero account balance).

**Recommendation for the harness:** prefer **opencode-native free models** (`opencode/...:free` family) — they bypass the OpenRouter free-tier rate-limit trap and require no extra credentials beyond the existing `auth.json`.

## 8. Implications for `abench` adapter (consumed by Tasks 12–13)

- **Driving mode**: spawn one `opencode run --format json --print-logs --log-level INFO --dir <workdir> --model <m> --agent <a> --dangerously-skip-permissions "<msg>"` subprocess per run. Read stdout line-by-line for live events; collect stderr separately (live wall-clock + bus events). No `opencode serve` / SSE / HTTP needed.
- **Canonical trace**: after the subprocess exits, run `opencode export <sessionID>` for the persisted record (aggregate tokens, cost, file diffs).
- **Getting the session id**: it appears on the very first stdout JSONL line as `sessionID`. The adapter should read it from the first event and remember it.
- **Cost/token defaults**: aggregated in `session.info.cost` / `session.info.tokens` (canonical) and also per-step in `step_finish.part`. Use the aggregate.
- **Tool/test detection**: shell tool name in opencode is `"bash"` (verified) with `state.input.command` holding the shell command — matches `MetricsCfg` defaults already shipped in Phase 1.
- **n_steps (ReAct chain length)**: count distinct `messageID` values among assistant parts, or equivalently `step_start` events.
- **Fixed system prompt**: not yet directly probed; the `--agent` flag selects an agent definition. The simplest path is to create a custom agent (`opencode agent create`) with the desired system prompt and select it via `--agent <name>` per run. Confirm in Task 13.
- **Pin both models**: the harness MUST set `small_model` to a free opencode-native model in the project's effective config, otherwise the title generator hits paid `claude-haiku-4.5` and aborts runs on zero-balance accounts. Options: write a per-project `opencode.json` inside the workdir copy before running, or pass both via flags if/when opencode supports a small-model flag.

## 9. Open follow-ups (defer to implementation)

- How does `opencode` pick up project-local `opencode.json`? (likely from cwd; confirm by dropping one into the workdir copy and observing `opencode debug config`.)
- Confirm `reasoning` / `patch` / `snapshot` part shapes when a model triggers them (current samples don't).
- Confirm `tool.state.status` values during a streaming tool call (only `completed` observed).
- Streaming behavior of `text` parts on long replies — does each model produce a single big `text` event, or multiple incremental ones?
