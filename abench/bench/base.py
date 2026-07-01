"""Core domain types for the benchmark layer + the AgentView/OracleView firewall.

A benchmark instance splits into two disjoint planes:
  - AgentView: everything the agent (and any augmentation) may legitimately see.
  - oracle (dict on Instance): gold patch / hidden tests / expected resolution —
    reachable ONLY via the full Instance, i.e. inside grade().

The firewall is structural: `agent_view()` projects the Instance onto an
AgentView type that simply has no `oracle` field, so oracle data is never
copied across. `assert_no_oracle_leak` is a defense-in-depth backstop on top of
that projection — e.g. a determined `object.__setattr__` injection onto an
AgentView is still caught by its `hasattr` check.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal, Protocol, runtime_checkable

_ORACLE_MARKERS: tuple[str, ...] = (
    "gold_patch",
    "hidden_test_patch",
    "expected_fail_to_pass",
    "expected_pass_to_pass",
    "reference_solution",
)


@dataclass(frozen=True)
class EnvSpec:
    """How to build/run the instance in isolation."""
    image: str
    build_system: Literal["maven", "gradle", "none"]
    module_map: dict[str, str] = field(default_factory=dict)
    workdir_mount: str = "/work"


@dataclass(frozen=True)
class TaskSpec:
    """The legitimate agent-facing task input (issue text or codegen spec)."""
    prompt_text: str
    allowed_context: tuple[str, ...] = ()


@dataclass(frozen=True)
class Anchors:
    """Legitimately-known static seeds for augmentation. NEVER the hidden tests."""
    existing_tests: tuple[str, ...] = ()
    issue_entrypoints: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentView:
    """Everything the agent may see. No oracle fields exist on this type."""
    instance_id: str
    repo: str
    task: TaskSpec
    anchors: Anchors
    env: EnvSpec


@dataclass(frozen=True)
class GradeResult:
    """Dual-grading result: official verdict + abench's own statistics."""
    resolved: bool | None
    evaluator: str
    standard_protocol: bool
    official_report: dict[str, Any] = field(default_factory=dict)
    abench: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Instance:
    """Full benchmark record. `oracle` holds gold/hidden data and is reachable
    only here (and thus only inside grade())."""
    instance_id: str
    repo: str
    task: TaskSpec
    anchors: Anchors
    env: EnvSpec
    # frozen=True blocks reassigning `oracle`, not in-place mutation of the dict
    # it points at; acceptable because adapters yield a fresh Instance per
    # load() (oracle dicts are never shared across instances).
    oracle: dict[str, Any] = field(default_factory=dict)

    def agent_view(self) -> AgentView:
        return AgentView(
            instance_id=self.instance_id,
            repo=self.repo,
            task=self.task,
            anchors=self.anchors,
            env=self.env,
        )


def assert_no_oracle_leak(view: AgentView) -> None:
    """Defensive backstop on top of the structural firewall: raise if an
    AgentView somehow carries oracle data. Checks field NAMES only (never field
    VALUES) so a task prompt legitimately mentioning a marker word is fine."""
    if hasattr(view, "oracle"):
        raise AssertionError("AgentView must not carry an `oracle` attribute")
    field_names = {f.name for f in dataclasses.fields(view)}
    leaked = field_names & set(_ORACLE_MARKERS)
    if leaked:
        raise AssertionError(f"oracle marker field(s) leaked into AgentView: {sorted(leaked)}")


@runtime_checkable
class BenchmarkAdapter(Protocol):
    """A benchmark plugged into the run pipeline. `id` is the registry key."""
    id: str

    def load(self, dataset: Path | None, subset: dict[str, Any] | None) -> Iterable[Instance]:
        ...

    def materialize(self, view: AgentView, workdir: Path) -> None:
        ...

    def grade(self, inst: Instance, source_diff: str, workdir: Path) -> GradeResult:
        ...
