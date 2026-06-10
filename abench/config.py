# abench/config.py
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

DEFAULT_TEST_PATTERNS = [
    "pytest",
    r"(npm|pnpm|yarn)( run)? test",
    r"go test",
    r"cargo test",
    r"(jest|vitest)",
    # JVM build tools (the verify subsystem already supports gradle/maven; keep
    # the metric's test-run detection in sync so Java runs aren't silently 0).
    r"(\./)?gradlew?\b.*\b(test|check)\b",
    r"(\./)?mvnw?\b.*\b(test|verify|integration-test)\b",
]


class Condition(BaseModel):
    name: str = Field(
        title="Name",
        description="Condition label (e.g. baseline, augmented).",
    )
    augmentation: str | None = Field(
        default=None,
        title="Augmentation",
        description=(
            "Path to the context-slice markdown injected for this condition; "
            "blank = no augmentation (baseline)."
        ),
    )
    overlay: str | None = Field(
        default=None,
        title="Overlay",
        description=(
            "Directory copied into the run workdir before the seed commit "
            "(per-session tool files); blank = none. '*.tmpl' files are "
            "rendered with overlay_env and written without the suffix."
        ),
    )


class ProviderCfg(BaseModel):
    id: str = Field(
        title="Provider id",
        description=(
            "Model prefix for this provider, e.g. 'kimi' → Model 'kimi/kimi-k2.6'. "
            "Add its API key via the Model field's 'Add API key' button (stored in "
            "opencode auth.json), or set an env var below."
        ),
    )
    base_url: str = Field(
        title="Base URL",
        description="OpenAI-compatible endpoint, e.g. https://host/v1",
    )
    models: list[str] = Field(
        default_factory=list,
        title="Model ids",
        description="Model ids this endpoint serves, e.g. kimi-k2.6.",
    )
    npm: str = Field(
        default="@ai-sdk/openai-compatible",
        title="SDK package",
        description=(
            "opencode provider SDK; the default works for any OpenAI-compatible API."
        ),
    )
    name: str | None = Field(
        default=None,
        title="Display name",
        description="Optional human label.",
    )
    api_key_env: str | None = Field(
        default=None,
        title="API key env var",
        description=(
            "Optional: read the key from this environment variable (rendered as "
            "{env:NAME}) instead of opencode auth.json."
        ),
    )


class SandboxCfg(BaseModel):
    """Filesystem/network isolation for the agent run. When ``mode='container'``
    the run workdir is the ONLY host path the agent can see, which closes the
    'agent reads the original off disk' leak vector. The toolchain + opencode
    live in the image (build with docker/Dockerfile.sandbox). Verify still runs
    on the host (it is the trusted measurement and needs no isolation)."""

    mode: Literal["none", "container"] = Field(
        default="none",
        title="Mode",
        description=(
            "'none' runs opencode directly on the host (current behaviour); "
            "'container' runs each agent run in an isolated container with only "
            "the run workdir mounted."
        ),
    )
    runtime: str = Field(
        default="docker",
        title="Container runtime",
        description="Container CLI to invoke: 'docker' or 'podman'.",
    )
    image: str = Field(
        default="abench-sandbox:latest",
        title="Sandbox image",
        description=(
            "Image carrying the toolchain + opencode. Built automatically from "
            "the bundled docker/Dockerfile.sandbox on first use (see auto_build), "
            "or point this at your own image. It must NOT contain the "
            "original/reference sources."
        ),
    )
    auto_build: bool = Field(
        default=True,
        title="Auto-build image",
        description=(
            "If the image is missing, build it automatically (once) from the "
            "Dockerfile before the first run — so nothing has to be built by "
            "hand. Turn off if you manage the image yourself."
        ),
    )
    dockerfile: str | None = Field(
        default=None,
        title="Dockerfile path",
        description=(
            "Dockerfile used for auto-build. Defaults to the bundled "
            "docker/Dockerfile.sandbox."
        ),
    )
    workdir_mount: str = Field(
        default="/work",
        title="Workdir mount path",
        description="Path the run workdir is bind-mounted to inside the container.",
    )
    network: str | None = Field(
        default=None,
        title="Network",
        description=(
            "Value for the runtime's --network (e.g. 'none' to block all egress). "
            "Leave empty for the default so the model endpoint stays reachable."
        ),
    )
    env_passthrough: list[str] = Field(
        default_factory=list,
        title="Env passthrough",
        description=(
            "Extra host env var NAMES to forward into the container (-e NAME). "
            "Any {env:NAME} referenced by the provider config is forwarded "
            "automatically. Only names are passed, never values."
        ),
    )
    cache_mounts: list[str] = Field(
        default_factory=list,
        title="Cache mounts",
        description=(
            "Extra 'HOST:CONTAINER[:ro]' bind mounts, e.g. a warmed dependency "
            "cache like '/home/me/.gradle:/root/.gradle:ro' to avoid re-download."
        ),
    )


class OpenCodeCfg(BaseModel):
    agent: str = Field(
        default="bench",
        title="Agent",
        description="OpenCode agent profile name to run.",
    )
    binary: str = Field(
        default="opencode",
        title="Binary",
        description="OpenCode executable name/path.",
    )
    small_model: str | None = Field(
        default=None,
        title="Small model override",
        description=(
            "opencode's helper model (titles/summaries). Defaults to the run's "
            "main model, so the bench uses one provider; set this only if you "
            "want a cheaper/faster helper, e.g. 'openrouter/...'."
        ),
    )
    idle_timeout_s: int | None = Field(
        default=600,
        title="Idle (no-output) timeout (s)",
        description=(
            "Kill a run that produces NO output for this long — a likely hang "
            "(stalled model/connection), so an unattended experiment never "
            "wedges forever on one run. Independent of the overall run timeout; "
            "empty/0 disables it."
        ),
    )
    providers: list[ProviderCfg] = Field(
        default_factory=list,
        title="Custom providers",
        description=(
            "Register OpenAI-compatible / custom endpoints so you can use "
            "'<id>/<model>' in Model."
        ),
    )
    sandbox: SandboxCfg = Field(
        default_factory=lambda: SandboxCfg(),
        title="Sandbox",
        description=(
            "Run each agent run inside an isolated container so it cannot read "
            "anything outside the run workdir (the original sources, the "
            "reference solution, other checkouts). Off by default."
        ),
    )


class MetricsCfg(BaseModel):
    test_command_patterns: list[str] = Field(
        default_factory=lambda: list(DEFAULT_TEST_PATTERNS),
        title="Test command patterns",
        description=(
            "Regexes matched against tool commands to count test runs "
            "(e.g. 'pytest', 'go test')."
        ),
    )
    shell_tool_names: list[str] = Field(
        default_factory=lambda: ["bash"],
        title="Shell tool names",
        description="Tool names treated as shell/command execution.",
    )
    read_tool_names: list[str] = Field(
        default_factory=lambda: ["read"],
        title="Read tool names",
        description="Tool names counted as file reads.",
    )
    search_tool_names: list[str] = Field(
        default_factory=lambda: ["grep", "glob", "list"],
        title="Search tool names",
        description="Tool names counted as code search (grep/glob/list).",
    )
    edit_tool_names: list[str] = Field(
        default_factory=lambda: ["edit", "write", "patch"],
        title="Edit tool names",
        description=(
            "Tool names counted as file edits — drives time_to_first_edit_s "
            "(opencode emits no patch parts, so edit tool calls are the signal)."
        ),
    )
    command_arg_keys: list[str] = Field(
        default_factory=lambda: ["command", "cmd", "script"],
        title="Command arg keys",
        description=(
            "Tool-arg keys whose value holds the shell command "
            "(matched against test_command_patterns)."
        ),
    )


class VerifyCfg(BaseModel):
    command: str | None = Field(
        default=None,
        title="Verify command",
        description="Build/test command. Leave blank to auto-detect (gradle/maven/pytest).",
    )
    enabled: bool = Field(
        default=True,
        title="Enabled",
        description="Run the build/test verification step after the agent finishes.",
    )
    timeout_s: int = Field(
        default=300,
        title="Verify timeout (s)",
        description="Max seconds for the verify command.",
    )


class IsolationCfg(BaseModel):
    nonce_prefix: bool = Field(
        default=True,
        title="Nonce prefix",
        description=(
            "Prepend a unique comment line to the system prompt so each run "
            "defeats provider prompt-cache reuse."
        ),
    )
    shuffle_order: bool = Field(
        default=True,
        title="Shuffle order",
        description=(
            "Randomize condition×repetition execution order to avoid ordering bias."
        ),
    )
    forbid_external_sources: bool = Field(
        default=True,
        title="Forbid external sources",
        description=(
            "Prepend ground rules forbidding the agent from using anything "
            "outside the project workdir — no .git/VCS history, no other copies "
            "of the project, no paths outside it, no internet — so results "
            "reflect solving from the project's own sources and tests rather "
            "than a leaked or memorized original."
        ),
    )
    # v2 heavyweight (not consumed in v1; placeholder for forward-compat):
    user_field_template: str | None = Field(
        default=None,
        title="User field template",
        description="Reserved for v2 (not used in v1).",
    )
    api_key_env_list: str | None = Field(
        default=None,
        title="API key env list",
        description="Reserved for v2 (not used in v1).",
    )


class Experiment(BaseModel):
    name: str = Field(
        title="Name",
        description="Experiment name.",
    )
    fixture_path: Path = Field(
        title="Fixture path",
        description="Working tree the agent edits (the stripped project).",
    )
    reference_path: Path = Field(
        title="Reference path",
        description="Ground-truth tree for comparison (the original project).",
    )
    task_prompt: str = Field(
        title="Task prompt",
        description="Task instructions — inline text or a path to a .md file.",
    )
    system_prompt: str = Field(
        title="System prompt",
        description="System prompt — inline text or a path to a .md file.",
    )
    model: str = Field(
        title="Model",
        description=(
            "Model identifier passed to OpenCode "
            "(e.g. opencode/deepseek-v4-flash-free)."
        ),
    )
    output_dir: Path = Field(
        title="Output dir",
        description="Directory where run artefacts are written.",
    )
    conditions: list[Condition] = Field(
        title="Conditions",
        description="Conditions to compare (baseline vs augmented).",
    )
    repetitions: int = Field(
        default=3,
        ge=1,
        title="Repetitions",
        description="Runs per condition.",
    )
    opencode: OpenCodeCfg = Field(
        default_factory=OpenCodeCfg,
        title="OpenCode",
        description="OpenCode agent/binary configuration.",
    )
    timeout_s: int | None = Field(
        default=None,
        title="Run timeout (s)",
        description=(
            "Max seconds per agent run, or empty for no limit (default). A hard "
            "task can take many minutes; use Cancel to stop a stuck run. Set a "
            "number only if you want a backstop against a wedged process."
        ),
    )
    min_seconds_between_runs: float = Field(
        default=0.0,
        title="Min seconds between runs",
        description="Throttle between runs to respect provider rate limits (0 = none).",
    )
    rate_limit_retries: int = Field(
        default=3,
        ge=0,
        title="Rate-limit retries",
        description=(
            "Retry a run this many times when the provider returns 429 (rate "
            "limit), with exponential backoff. 0 disables."
        ),
    )
    rate_limit_backoff_s: float = Field(
        default=10.0,
        ge=0,
        title="Rate-limit backoff (s)",
        description="Base backoff before a 429 retry; doubles each attempt (capped at 120s).",
    )
    metrics: MetricsCfg = Field(
        default_factory=MetricsCfg,
        title="Metrics",
        description="Tool-usage metric extraction configuration.",
    )
    verify: VerifyCfg = Field(
        default_factory=VerifyCfg,
        title="Verify",
        description="Build/test verification configuration.",
    )
    isolation: IsolationCfg = Field(
        default_factory=IsolationCfg,
        title="Isolation",
        description="Run-isolation configuration (cache busting, ordering).",
    )
    overlay_env: dict[str, str] = Field(
        default_factory=dict,
        title="Overlay env",
        description=(
            "Variables substituted into overlay '*.tmpl' files as ${NAME}. "
            "Values may use the '{env:NAME}' indirection, resolved from the "
            "process environment at run start."
        ),
    )
    target_file: str | None = Field(
        default=None,
        title="Target file",
        description="File the target method lives in — optional, for analysis.",
    )
    target_methods: list[str] | None = Field(
        default=None,
        title="Target methods",
        description="Method names under test — optional, for analysis.",
    )


def _resolve_text(value: str | None, base: Path) -> str | None:
    if value is None:
        return None
    candidate = base / value
    if candidate.is_file():
        return candidate.read_text()
    return value


def load_experiment(path: str | Path) -> Experiment:
    path = Path(path)
    base = path.parent
    data = yaml.safe_load(path.read_text())

    data["task_prompt"] = _resolve_text(data["task_prompt"], base)
    data["system_prompt"] = _resolve_text(data["system_prompt"], base)
    for cond in data.get("conditions", []):
        cond["augmentation"] = _resolve_text(cond.get("augmentation"), base)

    for cond in data.get("conditions", []):
        if cond.get("overlay"):
            cond["overlay"] = str((base / cond["overlay"]).resolve())

    data["fixture_path"] = str((base / data["fixture_path"]).resolve())
    data["reference_path"] = str((base / data["reference_path"]).resolve())
    data["output_dir"] = str((base / data["output_dir"]).resolve())

    exp = Experiment(**data)
    _validate(exp)
    return exp


def _validate(exp: Experiment) -> None:
    if not exp.fixture_path.exists():
        raise ValueError(f"fixture_path not found: {exp.fixture_path}")
    if not exp.reference_path.exists():
        raise ValueError(f"reference_path not found: {exp.reference_path}")
    out = exp.output_dir.resolve()
    ref = exp.reference_path.resolve()
    if ref == out or str(ref).startswith(str(out) + "/"):
        raise ValueError("reference_path must be outside output_dir (anti-leak)")
    if not exp.conditions:
        raise ValueError("at least one condition required")
    if exp.target_file is not None:
        full = exp.fixture_path / exp.target_file
        if not full.is_file():
            raise ValueError(
                f"target_file not found relative to fixture_path: {exp.target_file}"
            )
    for cond in exp.conditions:
        if cond.overlay is not None and not Path(cond.overlay).is_dir():
            raise ValueError(f"overlay dir not found: {cond.overlay} (condition {cond.name})")
