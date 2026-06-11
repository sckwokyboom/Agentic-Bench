# Design: Graph-Tipper as an installable OpenCode tool (bench-first)

- **Date:** 2026-06-11
- **Status:** approved (shape) — pending written-spec review
- **Repos touched:** Agentic-Bench (abench), Graph-Tipper (GT)
- **Related:** `docs/superpowers/plans/2026-06-10-reproducible-ab-pipeline.md` (the pipeline this evolves)

## 1. Problem

Wiring Graph-Tipper into an experiment today is non-trivial and machine-fragile:

- The agent-facing tool (`impact.ts`) is delivered **per-experiment** via an
  overlay copied into each run workdir (`overlays/impact/.opencode/tools/impact.ts`).
- The tool's config is rendered from a `.tmpl` whose `harness_path` is
  `${GRAPH_TIPPER_HOME}` — an **OS environment variable** that must be exported
  in the shell launching `abench`/`abench-ui` (it is NOT a UI field; the web UI
  has no OS-env input). This is the single biggest launch-friction and the
  source of the recurring "GRAPH_TIPPER_HOME is not set" surprise.

We want GT to instead be a **first-class, installable OpenCode tool**: installed
into an OpenCode environment once, enabled there, with the GT location set once
(no env var). The benchmark becomes one consumer of that installed tool.

**Chosen entry point: bench-first.** Build the "GT is an installable OpenCode
tool" mechanism and prove it through the benchmark (install into the sandbox
image + enable per-condition, replacing the overlay+env). Host-OpenCode install
polish is a deferred follow-up that reuses the same GT integration.

## 2. Goals / non-goals

**Goals**
- An `abench run` / UI run needs **zero OS env vars** for GT. The only
  machine-specific input ("where is GT checked out on the host", for the
  read-only mount) is supplied once via a UI-editable, gitignored machine-local
  registry — never committed, never an env var.
- GT's OpenCode tool(s) live canonically in the **GT repo** (`integrations/opencode/`,
  which already exists) and are installed into the sandbox image, not vendored
  per-experiment.
- The A/B contrast stays valid: `baseline` and other non-tool conditions must
  **not even see** the GT tool in their toolset; only the tool condition(s) get it.
- Back-compatible: existing `{env:NAME}` references keep working; the change is additive.

**Non-goals (YAGNI / deferred)**
- A slick host-OpenCode installer/UX (the integration is documented and usable;
  prettifying host install is later).
- A fully declarative `tools: [graph-tipper]` experiment block with auto-wiring
  (this is the natural evolution; not now).
- A registry for **secrets** (API keys). Keys keep their existing mechanism
  (provider `api_key_env` + opencode auth.json). This spec is about library/tool
  **paths**, not secrets.
- Running GT's Java CLI inside the container. The `impact` tool only runs GT's
  **Python** engine over pre-produced artifacts; the JDK-21 Java CLI runs at
  `produce_artifacts` time on the host. The image's JDK 17 is therefore fine.

## 3. Ground truth (verified 2026-06-11)

- **OpenCode 1.15.11 supports per-agent tool gating.** Config schema
  (`https://opencode.ai/config.json`): `$defs/AgentConfig/properties/tools` is
  `{object, additionalProperties: boolean}` (marked `@deprecated` in favour of a
  `permission` field, but functional in 1.15.x); a top-level `tools` map exists
  too. So a globally-installed tool can be disabled for specific agents/conditions.
- **GT already ships the integration.** `Graph-Tipper/integrations/opencode/`
  contains `README.md`, `impact.json.example`, and `tools/{impact.ts,crash_slice.ts}`.
  The README's install steps already include `~/.config/opencode/tools/` for
  "every project". So this is a wiring/packaging task, not a rewrite.
- **`impact.ts` reads per-project config** from `${worktree}/.opencode/impact.json`
  (`harness_path` + artifact paths + `total_tests`) and shells
  `python3 -m harness.impact.from_git` with `cwd=harness_path`.
- **Sandbox image** (`docker/Dockerfile.sandbox`): `eclipse-temurin:17-jdk`,
  installs `python3` + `git` + opencode; has **no ENTRYPOINT** and no OpenCode
  tools directory set up.
- **Project-local `.opencode/tools/` discovery works** in the container (risk-gate
  18.3 host half). Global `~/.config/opencode/tools/` is claimed by GT's README; to
  re-confirm in-image during implementation.

## 4. Design

### 4.1 Three layers (different lifecycles — keep them separate)

| Layer | What | Where it lives | Machine-specific? |
|---|---|---|---|
| **Glue** | `impact.ts` (+ `crash_slice.ts`) — thin OpenCode tools | installed into OpenCode (image now; host later) | no — portable |
| **Engine + path** | GT Python engine (`harness.impact.*`); `harness_path` | wherever GT is checked out / mounted | **yes — set once** |
| **Artifacts** | `methods/coverage/mutation.json`, `total_tests` for the repo under test | next to the project under test | yes — produced per repo |

### 4.2 Component changes

**A. Graph-Tipper repo — canonicalize the integration (minimal).**
- Treat `integrations/opencode/` as the single source of truth for the tool
  glue. No structural change required; possibly add a tiny `install.sh` that
  copies `tools/*.ts` into a target OpenCode tools dir and writes an
  `impact.json` from the example. (Confirm during planning whether the README
  steps suffice without a script.)

**B. Sandbox image — carry the tool, installed from the mounted GT.**
- Add an **ENTRYPOINT** script to `docker/Dockerfile.sandbox` that, on container
  start, installs GT's OpenCode tools into the container's global tools dir
  (`/root/.config/opencode/tools/`) from the mounted GT
  (`/opt/graph-tipper/integrations/opencode/tools/*.ts`), then `exec "$@"`.
  - GT stays the single source of truth (no vendored copy drift).
  - If GT is not mounted (non-GT experiments), the entrypoint is a no-op.
  - Alternative considered: COPY a vendored `impact.ts` at build. Rejected as
    default (drift vs GT); revisit only if entrypoint-time install proves flaky.

**C. abench — machine-local library registry + `{lib:}` resolver.**
- New gitignored file `.abench.local.json` at repo root, e.g.:
  ```json
  { "libraries": { "graph-tipper": "/mnt/d/Projects/Graph-Tipper" } }
  ```
  Committed sibling `.abench.local.example.json` documents the shape.
- New indirection token `{lib:NAME}`, resolvable wherever `{env:NAME}` is today
  (cache_mounts first; overlay_env if needed). Resolution order: registry →
  `{env:NAME}` fallback → the new fail-fast pre-flight error (already added in
  bench `f34e999`) listing what is missing and where to set it.
- A tiny registry module (read/write the JSON) + FastAPI endpoints
  (`GET/PUT /api/libraries`) + a small "Libraries" panel in the UI (mirrors the
  existing provider-credentials pattern). CLI reads the same file; optional
  `abench lib add <name> <path>` convenience command.

**D. abench — per-condition tool gating (replaces overlay-as-gate).**
- `Condition` gains `tools: list[str]` (default `[]`) — the GT tool names this
  condition enables (e.g. `[impact]`).
- The experiment declares the **gateable universe**, e.g.
  `opencode.gated_tools: [impact, crash_slice]` (the tools the image may carry).
- `build_opencode_config` writes, per condition, the agent's `tools` map that
  **disables every gated tool not in the condition's `tools` list**
  (`{crash_slice: false, impact: false}` for baseline; impact left enabled for
  the tool condition). Because installed tools default to enabled, baseline must
  explicitly disable them — that is the gate.
- **Correctness hazard — the gated universe must cover EVERY tool the image
  installs.** GT ships `impact.ts` AND `crash_slice.ts`; the entrypoint installs
  all of them. If `gated_tools` lists only `impact`, then `crash_slice` stays
  enabled-by-default and **leaks into baseline** — an A/B contamination. The
  plan must source the install set reliably so baseline disables ALL of them.
  Preferred: the entrypoint writes a manifest of installed tool names (e.g.
  `/root/.config/opencode/installed-tools.json`) that the run reads, rather than
  a hand-maintained `gated_tools` that can drift from what GT ships.
- Pick `tools` map vs newer `permission` field during planning; `tools` works in 1.15.x.

**E. abench — slim the overlay + drop the env.**
- `overlays/impact/` → `overlays/impact-artifacts/`: keeps ONLY the per-repo
  artifacts (`.impact/*`) and a **static** `.opencode/impact.json` (no `.tmpl`,
  no env): `harness_path` becomes the constant container path `/opt/graph-tipper`;
  artifact paths stay relative; `total_tests` stays a literal.
- Remove `impact.ts` from the overlay (now installed in the image).
- Remove `overlay_env.GRAPH_TIPPER_HOME`; `cache_mounts` uses `{lib:graph-tipper}`.

### 4.3 `experiment.yaml`: before → after

```yaml
# BEFORE
opencode:
  sandbox:
    cache_mounts: ["{env:GRAPH_TIPPER_HOME}:/opt/graph-tipper:ro"]
overlay_env: {GRAPH_TIPPER_HOME: /opt/graph-tipper}
conditions:
  - {name: baseline, augmentation: null}
  - {name: augmented-tool, augmentation: ./slices/impact-tool-briefing.md,
     overlay: ./overlays/impact}            # overlay carried BOTH glue + artifacts

# AFTER
opencode:
  gated_tools: [impact]                       # universe the image may carry
  sandbox:
    cache_mounts: ["{lib:graph-tipper}:/opt/graph-tipper:ro"]   # path from .abench.local.json
conditions:
  - {name: baseline, augmentation: null, tools: []}             # impact explicitly disabled
  - {name: augmented-tool, augmentation: ./slices/impact-tool-briefing.md,
     overlay: ./overlays/impact-artifacts, tools: [impact]}     # overlay = artifacts only
# overlay_env gone; GRAPH_TIPPER_HOME appears nowhere
```

### 4.4 Data flow

**Tool condition (`augmented-tool`):**
1. Runner resolves `{lib:graph-tipper}` from `.abench.local.json` → host path;
   mounts it ro at `/opt/graph-tipper`.
2. Container entrypoint installs `/opt/graph-tipper/integrations/opencode/tools/*.ts`
   → `/root/.config/opencode/tools/`.
3. Overlay drops per-repo artifacts + static `.opencode/impact.json`
   (`harness_path: /opt/graph-tipper`) into the workdir.
4. `build_opencode_config` enables `impact` for the `abench` agent.
5. Agent calls `impact` → `impact.ts` reads workdir `.opencode/impact.json` →
   `python3 -m harness.impact.from_git` (cwd `/opt/graph-tipper`) → markdown.

**Baseline:** same image (tool installed), but step 4 **disables** `impact`, and
there is no artifacts overlay → the model never sees or calls the tool. A/B clean.

## 5. Testing strategy

- **Unit — registry:** read/write `.abench.local.json`; missing file; malformed JSON.
- **Unit — `{lib:}` resolver:** registry hit; `{env:}` fallback; missing → the
  existing fail-fast pre-flight names it. Extend `_required_env_refs`/pre-flight
  to understand `{lib:}` (so a missing library path is reported the same clear way).
- **Unit — config builder:** for a condition with `tools: [impact]`, the agent
  config enables impact; for `tools: []`, every `gated_tools` entry is disabled.
- **Integration — container smoke (risk-gate 18.3, upgraded):** with GT mounted,
  tool condition → trace shows `impact` available + called + returns Tier-1/Tier-2/
  blind-spot markdown; baseline → `impact` absent from the toolset and never called.
- **UI:** `GET/PUT /api/libraries` round-trip; panel writes the gitignored file.

## 6. Migration / back-compat

- `{env:NAME}` keeps working; `{lib:NAME}` is additive. Existing experiments
  using `{env:GRAPH_TIPPER_HOME}` continue to run.
- The committed `picocli-putValue` experiment migrates to the new shape; old
  `overlays/impact/` is renamed/trimmed to `overlays/impact-artifacts/`.
- `.gitignore` gains `.abench.local.json`; `.abench.local.example.json` is committed.

## 7. Open implementation decisions (resolve in the plan)

1. **Tool install into image:** entrypoint-from-mounted-GT (preferred) vs vendored copy.
2. **Registry location:** `.abench.local.json` repo-local (preferred — discoverable,
   next to experiments) vs `~/.config/abench/libraries.json` (survives re-clones).
3. **Gating field:** OpenCode `tools` map (`@deprecated` but works) vs `permission`.
4. Whether GT needs a small `install.sh` or the README steps + image entrypoint suffice.

## 8. Deferred / future

- Host-OpenCode install UX (one command to enable GT's tools in your daily opencode).
- Declarative `tools: [graph-tipper]` block with descriptor-driven auto-wiring.
- Generalize the registry/gating to arbitrary third-party OpenCode tools.
