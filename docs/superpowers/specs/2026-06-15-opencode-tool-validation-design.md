# Design: OpenCode custom-tool validation mechanism (sub-project 1)

- **Date:** 2026-06-15
- **Status:** approved (shape) — pending written-spec review
- **Repo:** Agentic-Bench
- **Related:** the just-merged "GT as an installable OpenCode tool" work (`393fd08`); this is the foundation for a future UI tool-adding panel (sub-project 2, separate spec).

## 1. Problem & context

We want the bench to become a reusable harness for evaluating OpenCode tools: add a tool to an experiment's agent environment, **validate it immediately**, and surface load errors right away. Two blockers motivate this sub-project:

1. **A real bug:** in a container smoke run the agent invoked `bash impact` (a shell command) instead of the OpenCode `impact` tool — i.e. opencode did **not** expose the custom tool to the agent inside the sandbox. It loads fine on the host (host-half risk-gate passed) but not in the container. The model (`deepseek/deepseek-v4-flash`) is adequate for the task, so this is an environment/registration problem, not a model problem.
2. **No validation primitive:** there is currently no way to check "is this tool actually loaded and offered to the agent?" before/independent of a full experiment run.

This is **sub-project 1 of 2**. Sub-project 2 (a web-UI panel to add a tool + show validation results) is a separate spec that consumes the mechanism built here. Scope of "tool" here is **OpenCode custom tools only** (`.ts` files using `@opencode-ai/plugin`); skills/plugins are a later generalization.

## 2. Goals / non-goals

**Goals**
- A backend function `validate_tool(...)` that answers, for one OpenCode custom tool, in the **same sandbox the bench uses**: is it registered and offered to the agent, and if not, what went wrong — **without a model, API key, or network** (so it's instant and the corporate gateway is irrelevant).
- A CLI `abench validate-tool <experiment> <tool.ts>` exposing it (usable before the UI exists; the UI later calls the same function).
- Use that mechanism to **diagnose and fix** the container so `impact` registers (`registered: true`) — closing the `bash impact` bug.

**Non-goals (deferred)**
- The web-UI panel (sub-project 2).
- Skills / opencode plugins / MCP — only `.ts` custom tools now.
- **End-to-end** validation (a real agent run that actually *calls* the tool). Registration-level is the core; execution correctness is exercised by the actual experiment run.
- Generalising tool *placement* beyond what the bench already does.

## 3. Ground truth (verified locally on opencode 1.15.11, 2026-06-15)

- **`opencode debug agent <name>` is a model-free, key-free, network-free probe** that prints the resolved agent config as JSON, including a `tools` map. A custom tool dropped into `<dir>/.opencode/tools/<name>.ts` appears as `"tools": { "<name>": true, … }`.
- **It actually builds/transpiles the tool.** A deliberately broken tool (syntax error + unresolved import) makes the command exit **non-zero** and print to stderr:
  `ERROR … AggregateError: N errors building "<…>/.opencode/tools/<name>.ts"`, and the tool is **absent** from `.tools`. So the probe catches syntax errors, bad imports, and absence — not just filename enumeration.
- **`.opencode/tools/` (plural) is the correct directory**, and `import { tool } from "@opencode-ai/plugin"` resolves in opencode 1.15.11 (the SDK is provided by opencode itself — no extra install, no GT mount needed for *registration*).
- The container's opencode is installed differently from the host's (Dockerfile: `npm install -g opencode-ai || curl …/install`, unpinned) — the most likely reason host loads the tool but the container doesn't. The probe, run **inside the container**, will show the exact cause.

## 4. Design

### 4.1 `abench/tool_validation.py` (new)

```python
@dataclass
class ToolValidation:
    tool_name: str          # tool_src.stem
    registered: bool        # name present in agent's resolved .tools and truthy
    errors: list[str]       # build/transpile/load errors (from stderr), [] if OK
    exit_code: int          # opencode debug agent exit code
    raw: str                # raw stdout (resolved agent JSON, when exit==0)

def validate_tool(tool_src: Path, *, sandbox: SandboxCfg,
                  agent: str = "abench") -> ToolValidation: ...
```

Behaviour:
1. Build a throwaway temp workdir:
   - `<tmp>/.opencode/tools/<name>.ts` ← copy of `tool_src` (`name = tool_src.stem`);
   - `<tmp>/opencode.json` ← minimal config defining `agent` with a placeholder `prompt` and `model` (the probe is model-free; a syntactically-valid model id is enough — reuse the experiment's model when available).
2. Run `opencode debug agent <agent> --dir <tmp> --print-logs --log-level DEBUG`:
   - `sandbox.mode == "container"` → wrap in `docker run --rm -v <tmp>:/work -w /work <image> opencode debug agent <agent> --dir /work …` (reuse/generalise the container wrapper already in `opencode_client.build_run_command`; **no** provider `-e` env and **no** `cache_mounts` are needed — registration neither runs the model nor executes the tool body);
   - `sandbox.mode == "none"` → run `opencode` directly with `--dir <tmp>`.
3. Parse:
   - `exit == 0` → parse stdout JSON; `registered = bool(json.get("tools", {}).get(name))`; `errors = []`.
   - `exit != 0` → `registered = False`; `errors` = the `… errors building "…<name>.ts"` / `AggregateError` lines extracted from stderr.
4. Clean up the temp workdir; return `ToolValidation`.

One clear responsibility (validate one tool in a sandbox); pure-ish except the subprocess; easy to unit-test by mocking the subprocess result.

### 4.2 CLI — `abench validate-tool <experiment.yaml> <path/to/tool.ts>`

Loads the experiment (for its `sandbox` + `agent`), calls `validate_tool`, prints either
`✓ <name> registered` or `✗ <name> NOT registered` followed by the captured errors; exit 0/1 accordingly. This is the first usable interface and the on-server diagnostic for `impact`.

### 4.3 Container fix (diagnosis-driven)

Run `abench validate-tool experiment-tool-smoke.yaml <GT>/integrations/opencode/tools/impact.ts` **in the container** on the server. The output names the cause; apply the matching fix to `docker/Dockerfile.sandbox` until `impact` is `registered: true`. Most likely: **pin the opencode version** in the image to match the working host (1.15.x); possibly ensure the `@opencode-ai/plugin` SDK / Bun runtime resolves. Done-criterion: `validate-tool` reports `impact registered: true` inside the container, and a subsequent smoke run shows the agent calling the `impact` tool (not `bash impact`).

## 5. Data flow

`tool.ts` → temp workdir (`.opencode/tools/<name>.ts` + `opencode.json`) → `opencode debug agent <agent> --dir …` (in sandbox) → exit code + stdout JSON + stderr → `ToolValidation{registered, errors}`.

## 6. Testing

- **Unit — output parser** (no opencode): feed captured samples — (a) good agent JSON with `tools:{x:true}` → `registered`, (b) JSON without the tool → not registered, (c) non-zero exit + `AggregateError: … building x.ts` stderr → not registered + error captured.
- **Unit — temp-workdir builder:** the tool lands at `.opencode/tools/<name>.ts` and `opencode.json` defines the agent.
- **Integration (host, `mode: none`, no docker):** `validate_tool` on a real good `.ts` → `registered: true, errors: []`; on a broken `.ts` (syntax error) → `registered: false` with a non-empty error. (These mirror the verified 1.15.11 behaviour above.)
- **Container + `impact` diagnosis:** on the server (no docker locally) — part of §4.3.

## 7. Open / diagnosis-driven items

- The exact container fix (§4.3) is determined by the probe output on the server.
- Whether `opencode debug agent` needs a *resolvable provider* for the placeholder model (locally it accepted `deepseek/deepseek-chat` with no key). If it does, reuse the experiment's configured model id (still no key needed). The integration test pins this down.

## 8. Deferred — sub-project 2 (separate spec)

A web-UI "Tools" panel on the experiment editor: add a tool (upload/path), click validate, render `ToolValidation` (registered ✓/✗ + errors) inline. Pure frontend + a thin FastAPI endpoint that calls `validate_tool`. Generalisation to skills/plugins also later.
