# Design: secure model-reachability validation (sub-project 3)

- **Date:** 2026-06-15
- **Status:** approved (shape) — pending written-spec review
- **Repo:** Agentic-Bench
- **Related:** sub-project 1 (`abench validate-tool`, `opencode debug agent` probe) — this mirrors its sandbox-probe structure for the model endpoint. UI wiring is sub-project 3b (separate).

## 1. Problem & context

The UI's model check (`abench_ui/validate.py`) is **advisory and shallow**: it only checks the model id is in the HOST opencode's catalog (`opencode models <provider>`). It does NOT use the experiment's provider/`base_url`, never calls the endpoint with the key, and never runs from the environment the experiment actually uses (the container). So it shows "Available" for a model that is in fact unreachable — then the experiment fails at runtime with "model unavailable" after the operator has committed to a run. For an experiment using a **custom** provider (`deepseek` → `api.deepseek.com`), the host catalog knows nothing about it, so the check is doubly useless.

Two operator-facing problems: (a) the false "Available"; (b) the API key has to be exported as an OS env var because the UI's key button writes the HOST opencode `auth.json`, which the container's opencode never sees.

**Hard constraint (operator):** the API key must never leak — not into git, logs, traces, error text, process args, or anywhere except the configured provider endpoint.

This is **sub-project 3 (backend + CLI)**. UI wiring (a "Test" button + Run-gating in the React app) is **sub-project 3b**, a separate spec.

## 2. Decided parameters (from brainstorming)

- **Key storage:** opencode `auth.json` (`~/.local/share/opencode/auth.json`, outside the repo).
- **Where the probe runs:** the experiment's sandbox — inside the container for `mode: container` (catches the corporate gateway / egress / CA), on the host for `mode: none`.
- **Probe type:** a 1-token chat completion to the configured model (definitive — exactly what the run does; ~free for DeepSeek).
- **Gating:** block-with-override (don't auto-launch a long run against an unreachable model; the operator can force).
- **Scope now:** backend + CLI. UI = 3b.

## 3. Security invariants (non-negotiable)

- The key is **never** written to `experiment.yaml`, code, or git history.
- The key is **never** emitted to `run.log`/`debug.log`, `trace.json`, `safe_trace`, the reachability API response, or any error/diagnostic text. The probe's captured output is **scrubbed** of the key before it is returned or logged (an endpoint may echo the request/key in an error).
- The key is **never** placed in process `argv` (`docker run -e NAME` forwards by NAME from the abench subprocess env — value not in argv / `docker inspect`).
- The key is sent **only** to the configured `base_url`, nowhere else.
- On disk it lives only in opencode `auth.json` (its standard store, outside the repo).
- **Out of scope (flagged):** during a real RUN the key is in the container env, so the sandboxed agent's `bash` could read it — closing that needs a key-injecting egress proxy (a separate future effort). The reachability **probe** has no agent, so this does not apply to validation.

## 4. Design

### 4.1 Key source — `auth.json` → subprocess env (removes the env-export friction)

- Add `read_credential(provider: str) -> str | None` to `abench_ui/providers.py` (reads `auth.json[provider]["key"]`; returns None if absent). It returns the secret **only** into abench's memory for forwarding — never logged.
- When abench launches a container (run OR probe), for each provider with `api_key_env` set, it loads the key (auth.json first, then OS env fallback) and puts it in the **subprocess env dict**; the existing `-e NAME` (name-only) forwards it into the container. So a UI-entered key (auth.json) reaches the run automatically — no manual `export`.
- **Pre-flight update:** `runner._preflight_env` currently requires each provider's `api_key_env` to be in `os.environ`. Change it to accept the key from **either** `os.environ` **or** `auth.json`, so the auth.json-only case does not fail pre-flight falsely. (A small `providers.has_credential(provider)` helper; keep the clear error when neither source has it.)

### 4.2 Reachability probe

- **`abench/model_probe.py`** — a standalone, **stdlib-only** script (no abench imports, runs in the bare image which has python3). Args: `base_url model key_env_name`. It reads the key from `os.environ[key_env_name]`, sends `POST {base_url}/chat/completions` with `{"model": model, "messages": [{"role":"user","content":"ping"}], "max_tokens": 1}` and header `Authorization: Bearer <key>` (10s timeout), and prints a JSON verdict to stdout:
  `{"reachable": bool, "reason": "ok|auth|model_not_found|network|tls|http_<code>", "detail": "<short, KEY-SCRUBBED>"}`.
  Status mapping: 200 → ok; 401/403 → auth; 404, or 400 whose body names the model → model_not_found; `URLError`/timeout → network; SSL cert error → tls; other → `http_<code>`. The script scrubs the key from `detail` (replace the key substring with `***`).
- **`abench/reachability.py`** — orchestrator: `validate_reachability(provider_cfg, model, *, sandbox, key_env_name) -> ReachabilityResult{reachable, reason, detail}`.
  - host (`mode: none`): `subprocess.run(["python3", "<model_probe.py path>", base_url, model, key_env_name], env={**probe_env})`.
  - container: `docker run --rm -e <key_env_name> -v <model_probe.py>:/probe.py:ro <image> python3 /probe.py <base_url> <model> <key_env_name>` — base_url/model in argv (not secret), key via `-e` name-only (value in the abench subprocess env, read from auth.json). Reuse the network/runtime fields from `SandboxCfg`.
  - parse the probe's JSON stdout into `ReachabilityResult`; on non-JSON / non-zero exit, `reachable=False, reason="probe_failed", detail=<scrubbed stderr tail>`.

### 4.3 API + CLI

- **CLI:** `abench validate-model <experiment.yaml>` — loads the experiment, resolves provider+model+sandbox+key (auth.json/env), runs `validate_reachability`, prints `✓ <model> reachable` or `✗ <model> unreachable — <reason>: <detail>`; exit 0/1. Never prints the key.
- **API:** `POST /api/validate/reachability {experiment_name}` → `{reachable, reason, detail}` (3b consumes it).

### 4.4 Gating (backend support; UI in 3b)

The backend exposes the verdict; the UI (3b) shows it at config time and **blocks Run with an override** when `reachable=False`. (Backend stays advisory-capable; the gate lives in the UI so a CLI `abench run` is unaffected unless we later add a `--require-reachable` flag — out of scope now.)

### 4.5 Leak audit

Audit the run + validation paths for places the key could surface and add scrubbing where missing: the docker-command log line (already `-e NAME` name-only — verify), `trace`/`safe_trace`, error messages, the new probe's stdout/stderr. Add a unit test asserting the key never appears in the reachability result or a representative log line.

## 5. Data flow

UI/CLI → load experiment → resolve key (auth.json → env fallback) into subprocess env → run `model_probe.py` in the sandbox (`-e KEY` name-only) → probe POSTs 1-token completion to `base_url` → JSON verdict (key-scrubbed) → `ReachabilityResult` → CLI prints / API returns. Key never touches argv, logs, trace, or the response.

## 6. Testing

- **Unit — verdict mapping** (`model_probe.py`): feed canned (status, body) → correct `reason`; assert the key is scrubbed from `detail`.
- **Unit — command builder** (`reachability.py`): host vs container argv; key passed via `-e <NAME>` name-only (assert the key VALUE is never in argv); base_url/model present.
- **Unit — orchestration** (mock subprocess): good JSON → reachable; non-JSON/non-zero → `probe_failed`.
- **Unit — pre-flight**: provider key present in auth.json but NOT os.environ → pre-flight passes (no false failure); absent in both → clear error.
- **Unit — leak guard**: a `ReachabilityResult` and the logged command line never contain a sample key string.
- **Integration (host, opt-in)**: against a real endpoint only if a key is present in the env/auth.json; otherwise skipped. Container probe verified on the server.

## 7. Scope / non-goals

- **In:** key delivery from auth.json + pre-flight update; `model_probe.py` + `reachability.py`; `abench validate-model` CLI + `/api/validate/reachability`; leak audit/scrubbing.
- **3b (next spec):** React UI — replace the advisory "Available" chip with a real "Test reachability" action + result, and gate Run with an override.
- **Out:** protecting the key from the agent during a RUN (needs an egress proxy — future); non-OpenAI-compatible providers; skills/tools (sub-projects 1/2).

## 8. Open items

- Whether `model_probe.py` is best **mounted** (`-v`) into the container (chosen) vs `python3 -c` inline — mounting keeps it testable as a file; confirm the mount path doesn't collide with the run workdir mount (use a distinct path like `/probe.py`).
- Some OpenAI-compatible endpoints reject `max_tokens:1` oddly; if so, fall back to `GET {base_url}/models` for auth+endpoint reachability and treat model-membership as best-effort. The integration test pins down DeepSeek's behaviour.
