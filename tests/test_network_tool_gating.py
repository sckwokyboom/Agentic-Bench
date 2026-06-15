# tests/test_network_tool_gating.py
"""`forbid_external_sources` (default on) declares "no internet", but opencode
enables the built-in `webfetch` tool by default — a zero-friction network egress
that, on host-mode runs, only the prompt guard discouraged. The bench now
disables `webfetch` whenever external sources are forbidden, enforcing the
already-declared policy at the tool level.

Caveat captured for the record: `bash` can still curl, so this is a PARTIAL
control on host; the container sandbox is the real network boundary and the
cheating detector is the post-hoc backstop. Disabling `webfetch` simply removes
the obvious, explicitly-network tool."""
from abench.config import Condition, Experiment, MetricsCfg, OpenCodeCfg
from abench.runner import _agent_tools_for


def _exp(tmp_path, *, forbid_external_sources=True, allow_subagents=True,
         tools_lib=None, tools=()):
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
    # `allow_subagents=True` by default here so the `task` gate doesn't enter
    # these expectations — this file isolates the webfetch axis.
    exp.isolation.forbid_external_sources = forbid_external_sources
    return exp


def test_webfetch_disabled_when_external_sources_forbidden(tmp_path):
    exp = _exp(tmp_path, forbid_external_sources=True)
    assert _agent_tools_for(exp, exp.conditions[0]) == {"webfetch": False}


def test_webfetch_enabled_when_external_sources_allowed(tmp_path):
    exp = _exp(tmp_path, forbid_external_sources=False)
    assert _agent_tools_for(exp, exp.conditions[0]) is None


def test_both_gates_compose_at_real_defaults(tmp_path):
    """The real default (forbid_external_sources on, allow_subagents off) disables
    BOTH the sub-agent spawner and the network tool."""
    exp = _exp(tmp_path, forbid_external_sources=True, allow_subagents=False)
    assert _agent_tools_for(exp, exp.conditions[0]) == {
        "task": False, "webfetch": False,
    }
