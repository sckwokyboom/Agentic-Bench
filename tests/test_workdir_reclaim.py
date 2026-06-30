# tests/test_workdir_reclaim.py
"""After a container run, the agent's build artifacts (build/, .gradle/, target/)
in the bind-mounted workdir are owned by ROOT (the container's default user).
That blocks host-side gradle verify — gradle fails before tests with "Unable to
delete directory '<wd>/build/classes/...'" — and also rmtree cleanup. The runner
reclaims ownership via a throwaway root container before any host-side workdir
op. These pin that behavior."""
import os
import subprocess

from abench import runner
from abench.config import SandboxCfg
from abench.runner import _reclaim_workdir_ownership


def test_reclaim_builds_chown_container_command(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, *a, **k: calls.append(cmd))
    sb = SandboxCfg(mode="container", image="abench-sandbox:latest",
                    runtime="docker", workdir_mount="/work")
    _reclaim_workdir_ownership(sb, "/tmp/abench-xyz")
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[:3] == ["docker", "run", "--rm"]
    assert "--entrypoint" in cmd and "chown" in cmd  # bypass the image entrypoint
    assert "-v" in cmd and "/tmp/abench-xyz:/work" in cmd
    assert "-R" in cmd
    assert f"{os.getuid()}:{os.getgid()}" in cmd  # chown back to the host user
    assert cmd[-1] == "/work"


def test_reclaim_noop_in_host_mode(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))
    _reclaim_workdir_ownership(SandboxCfg(mode="none"), "/tmp/x")
    assert calls == []  # nothing to reclaim when the agent ran on the host


def test_reclaim_never_raises(monkeypatch):
    def explode(*a, **k):
        raise OSError("docker gone")
    monkeypatch.setattr(subprocess, "run", explode)
    sb = SandboxCfg(mode="container", image="img", runtime="docker",
                    workdir_mount="/work")
    _reclaim_workdir_ownership(sb, "/tmp/x")  # must not raise — cleanup is best-effort


def test_runner_reclaims_after_agent_run(tmp_path, monkeypatch):
    """run_experiment must call the reclaim hook after the agent run (here
    mode=none, so the helper itself no-ops, but the call site must exist so the
    container path is covered)."""
    from abench.config import Condition, Experiment, MetricsCfg, OpenCodeCfg
    from abench.opencode_client import RunResult
    from abench.trace_model import Trace

    seen = []
    monkeypatch.setattr(runner, "_reclaim_workdir_ownership",
                        lambda sb, wd: seen.append((sb, wd)))

    class _Client:
        def run_task(self, *, workdir, system_prompt, model, user_message,
                     timeout_s, agent_tools=None, on_event, log_sink=None,
                     debug_sink=None, cancel_event=None, temperature=None):
            on_event({"type": "message.start"})
            return RunResult(
                trace=Trace(started_at=0.0, ended_at=1.0, finished=True),
                raw_session=None)

    fixture = tmp_path / "fix"; fixture.mkdir(); (fixture / "a.py").write_text("x=1\n")
    reference = tmp_path / "ref"; reference.mkdir()
    exp = Experiment(
        name="r", fixture_path=fixture, reference_path=reference,
        task_prompt="t", system_prompt="s", model="m",
        output_dir=tmp_path / "runs", repetitions=1,
        conditions=[Condition(name="baseline", tools=[])],
        opencode=OpenCodeCfg(sandbox=SandboxCfg(mode="none")),
        metrics=MetricsCfg())
    exp.isolation.shuffle_order = False
    exp.verify.enabled = False
    runner.run_experiment(exp, lambda e: _Client())
    assert len(seen) == 1
    assert seen[0][0].mode == "none"
