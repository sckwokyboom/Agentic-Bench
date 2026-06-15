# tests/test_subagent_gating.py
"""opencode's `task` tool spawns sub-agents whose individual steps never reach
our exported trace (so they're unauditable by the cheating detector) and which
don't inherit the run's grounding guard (so they're unconstrained re: network /
outside-FS). The bench therefore disables subagent-spawning for EVERY run by
default — each run stays a single, fully-traced, guard-bound agent. An
experiment can opt back in with `opencode.allow_subagents: true`."""
from abench.config import Condition, Experiment, MetricsCfg, OpenCodeCfg
from abench.runner import _agent_tools_for


def _exp(tmp_path, *, tools_lib=None, allow_subagents=False, tools=()):
    exp = Experiment(
        name="x",
        fixture_path=tmp_path / "fix",
        reference_path=tmp_path / "ref",
        task_prompt="t", system_prompt="s", model="m",
        output_dir=tmp_path / "runs", repetitions=1,
        conditions=[Condition(name="c", tools=list(tools))],
        opencode=OpenCodeCfg(tools_lib=tools_lib, allow_subagents=allow_subagents),
        metrics=MetricsCfg(),
    )
    # Isolate the sub-agent (`task`) axis: turn OFF the external-sources gate so
    # the network-tool gate (webfetch) doesn't enter these expectations. The
    # webfetch gate is covered in test_network_tool_gating.py.
    exp.isolation.forbid_external_sources = False
    return exp


def test_task_disabled_by_default_without_tools_lib(tmp_path):
    """The common case (no tools_lib) still must disable `task` — previously
    this returned None and left subagent-spawning fully enabled."""
    exp = _exp(tmp_path)
    assert _agent_tools_for(exp, exp.conditions[0]) == {"task": False}


def test_allow_subagents_true_keeps_task_enabled(tmp_path):
    """Opt-in escape hatch: no overrides at all when subagents are allowed and
    there's no tools_lib gating to apply."""
    exp = _exp(tmp_path, allow_subagents=True)
    assert _agent_tools_for(exp, exp.conditions[0]) is None


def test_task_disabled_merges_with_tools_lib(tmp_path, monkeypatch):
    """The subagent gate composes with the per-condition GT-universe gate: the
    enabled tool stays on, the rest of the universe is off, and `task` is off."""
    from abench import libraries
    monkeypatch.setattr(libraries, "load_registry",
                        lambda: {"graph-tipper": tmp_path / "gt"})
    monkeypatch.setattr(libraries, "discover_opencode_tools",
                        lambda _p: {"impact", "crash_slice"})
    exp = _exp(tmp_path, tools_lib="graph-tipper", tools=["impact"])
    assert _agent_tools_for(exp, exp.conditions[0]) == {
        "impact": True, "crash_slice": False, "task": False,
    }


def test_allow_subagents_true_with_tools_lib_omits_task(tmp_path, monkeypatch):
    """With subagents allowed, the GT-universe gate is unchanged and `task` is
    not added."""
    from abench import libraries
    monkeypatch.setattr(libraries, "load_registry",
                        lambda: {"graph-tipper": tmp_path / "gt"})
    monkeypatch.setattr(libraries, "discover_opencode_tools",
                        lambda _p: {"impact", "crash_slice"})
    exp = _exp(tmp_path, tools_lib="graph-tipper", tools=["impact"],
               allow_subagents=True)
    assert _agent_tools_for(exp, exp.conditions[0]) == {
        "impact": True, "crash_slice": False,
    }
