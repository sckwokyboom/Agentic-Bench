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
    name: str
    augmentation: str | None = None


class OpenCodeCfg(BaseModel):
    agent: str = "bench"
    binary: str = "opencode"


class MetricsCfg(BaseModel):
    test_command_patterns: list[str] = Field(
        default_factory=lambda: list(DEFAULT_TEST_PATTERNS))
    shell_tool_names: list[str] = Field(default_factory=lambda: ["bash"])
    read_tool_names: list[str] = Field(default_factory=lambda: ["read"])
    search_tool_names: list[str] = Field(
        default_factory=lambda: ["grep", "glob", "list"])
    command_arg_keys: list[str] = Field(
        default_factory=lambda: ["command", "cmd", "script"])


class VerifyCfg(BaseModel):
    command: str | None = None          # override; otherwise auto-detect at run time
    enabled: bool = True
    timeout_s: int = 300


class IsolationCfg(BaseModel):
    nonce_prefix: bool = True            # uuid4 comment line at top of system_prompt
    shuffle_order: bool = True           # randomize condition×rep order
    # v2 heavyweight (not consumed in v1; placeholder for forward-compat):
    user_field_template: str | None = None
    api_key_env_list: str | None = None


class Experiment(BaseModel):
    name: str
    fixture_path: Path
    reference_path: Path
    task_prompt: str
    system_prompt: str
    model: str
    output_dir: Path
    conditions: list[Condition]
    repetitions: int = 3
    opencode: OpenCodeCfg = Field(default_factory=OpenCodeCfg)
    timeout_s: int = 600
    min_seconds_between_runs: float = 0.0
    metrics: MetricsCfg = Field(default_factory=MetricsCfg)
    verify: VerifyCfg = Field(default_factory=VerifyCfg)
    isolation: IsolationCfg = Field(default_factory=IsolationCfg)
    target_file: str | None = None
    target_methods: list[str] | None = None


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
