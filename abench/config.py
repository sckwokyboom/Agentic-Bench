# abench/config.py
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

DEFAULT_TEST_PATTERNS = [
    "pytest",
    r"(npm|pnpm|yarn)( run)? test",
    r"go test",
    r"cargo test",
    r"(jest|vitest)",
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
    timeout_s: int = Field(
        default=600,
        title="Run timeout (s)",
        description="Max seconds per agent run.",
    )
    min_seconds_between_runs: float = Field(
        default=0.0,
        title="Min seconds between runs",
        description="Throttle between runs to respect provider rate limits (0 = none).",
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
