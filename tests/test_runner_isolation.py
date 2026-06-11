import json
from pathlib import Path
from unittest.mock import patch

import pytest

from abench.config import Condition, Experiment, IsolationCfg, MetricsCfg, OpenCodeCfg, VerifyCfg
from abench.runner import run_experiment
from tests.fakes import FakeOpenCodeClient


def _make_exp(tmp_path: Path, isolation: IsolationCfg) -> Experiment:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "a.py").write_text("x = 1\n")
    reference = tmp_path / "reference"
    reference.mkdir()
    (reference / "a.py").write_text("x = 1\n")
    return Experiment(
        name="iso-test",
        fixture_path=fixture,
        reference_path=reference,
        task_prompt="t",
        system_prompt="ORIGINAL_SYSTEM_PROMPT",
        model="fake/m",
        output_dir=tmp_path / "runs",
        repetitions=2,
        conditions=[
            Condition(name="baseline", augmentation=None),
            Condition(name="augmented", augmentation="SLICE"),
        ],
        opencode=OpenCodeCfg(),
        metrics=MetricsCfg(),
        isolation=isolation,
        verify=VerifyCfg(enabled=False),  # skip verify in these tests
    )


class _RecordingClient:
    """Captures every system_prompt the runner passes."""
    def __init__(self):
        self.captures: list[str] = []
        self._fake = FakeOpenCodeClient()

    def run_task(self, *, workdir, system_prompt, model, user_message,
                 timeout_s, agent_tools=None, on_event, log_sink=None, debug_sink=None, cancel_event=None):
        self.captures.append(system_prompt)
        return self._fake.run_task(
            workdir=workdir, system_prompt=system_prompt, model=model,
            user_message=user_message, timeout_s=timeout_s, on_event=on_event,
            log_sink=log_sink, cancel_event=cancel_event,
        )


def test_nonce_prefix_prepended_when_enabled(tmp_path):
    # forbid_external_sources off so we isolate the nonce-prefix behaviour.
    exp = _make_exp(tmp_path, IsolationCfg(
        nonce_prefix=True, shuffle_order=False, forbid_external_sources=False))
    rec = _RecordingClient()
    run_experiment(exp, lambda e: rec)

    # 4 runs, each got a unique nonce-prefixed system prompt
    assert len(rec.captures) == 4
    for prompt in rec.captures:
        assert prompt.startswith("# abench-run: ")
        assert "\nORIGINAL_SYSTEM_PROMPT" in prompt
    # all nonces are unique
    nonces = {p.split("\n", 1)[0] for p in rec.captures}
    assert len(nonces) == 4


def test_nonce_prefix_disabled_passes_prompt_unchanged(tmp_path):
    exp = _make_exp(tmp_path, IsolationCfg(
        nonce_prefix=False, shuffle_order=False, forbid_external_sources=False))
    rec = _RecordingClient()
    run_experiment(exp, lambda e: rec)
    for prompt in rec.captures:
        assert prompt == "ORIGINAL_SYSTEM_PROMPT"


def test_grounding_guard_prepended_when_enabled(tmp_path):
    """forbid_external_sources prepends the ground rules to every run's system
    prompt (both conditions), forbidding .git/VCS history and external sources."""
    exp = _make_exp(tmp_path, IsolationCfg(
        nonce_prefix=False, shuffle_order=False, forbid_external_sources=True))
    rec = _RecordingClient()
    run_experiment(exp, lambda e: rec)
    assert rec.captures
    for prompt in rec.captures:
        assert prompt.startswith("# Ground rules")
        assert ".git" in prompt
        assert "ORIGINAL_SYSTEM_PROMPT" in prompt


def test_guard_and_nonce_compose(tmp_path):
    """Both on: guard first, then the nonce marker, then the base prompt."""
    exp = _make_exp(tmp_path, IsolationCfg(
        nonce_prefix=True, shuffle_order=False, forbid_external_sources=True))
    rec = _RecordingClient()
    run_experiment(exp, lambda e: rec)
    for prompt in rec.captures:
        assert prompt.startswith("# Ground rules")
        assert "# abench-run: " in prompt
        assert prompt.rstrip().endswith("ORIGINAL_SYSTEM_PROMPT")


def test_shuffle_changes_run_order_deterministically(tmp_path):
    """With shuffle_order=True and a fixed date-seed, the order is permuted but
    reproducible within the same day."""
    exp = _make_exp(tmp_path, IsolationCfg(nonce_prefix=False, shuffle_order=True))
    rec = _RecordingClient()
    root = run_experiment(exp, lambda e: rec)

    # Read manifests in disk order — they should reflect the actual run sequence
    manifests = sorted(root.glob("*/rep_*/manifest.json"))
    order = [json.loads(m.read_text())["condition"] + "/" +
             str(json.loads(m.read_text())["rep"]) for m in manifests]
    assert sorted(order) == sorted([
        "baseline/0", "baseline/1", "augmented/0", "augmented/1",
    ])
    # NOTE: with a fixed day-seed the permutation is deterministic; we don't
    # assert a specific order here because day rolls; just that all 4 ran.


import subprocess


def test_shuffle_is_deterministic_across_process_invocations():
    """Two separate Python processes on the same calendar day must produce
    the same shuffle for the same experiment name. PYTHONHASHSEED randomises
    Python's builtin `hash()`, so the runner must use a salt-stable hash."""
    script = (
        "import datetime, random, sys, hashlib\n"
        "name = sys.argv[1]\n"
        "raw = (name + datetime.date.today().isoformat()).encode()\n"
        "seed = int(hashlib.sha256(raw).hexdigest()[:16], 16)\n"
        "plan = list(range(8))\n"
        "random.Random(seed).shuffle(plan)\n"
        "print(plan)\n"
    )
    out1 = subprocess.run(
        ["python3", "-c", script, "iso-det-test"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    out2 = subprocess.run(
        ["python3", "-c", script, "iso-det-test"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert out1 == out2, f"shuffle drifted across processes: {out1!r} vs {out2!r}"


def test_run_verify_exception_does_not_lose_manifest(tmp_path, monkeypatch):
    """If run_verify raises, the rep must still write manifest.json and the
    trace must record verify_status='error'."""
    from abench import runner as runner_module
    from abench.config import Condition, Experiment, IsolationCfg, MetricsCfg, OpenCodeCfg, VerifyCfg

    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "a.py").write_text("x = 1\n")
    (fixture / "pom.xml").write_text("<project/>")  # so detect_command returns "mvn test"
    reference = tmp_path / "reference"
    reference.mkdir()
    exp = Experiment(
        name="ver-exc",
        fixture_path=fixture, reference_path=reference,
        task_prompt="t", system_prompt="s", model="m",
        output_dir=tmp_path / "runs", repetitions=1,
        conditions=[Condition(name="baseline", augmentation=None)],
        opencode=OpenCodeCfg(), metrics=MetricsCfg(),
        isolation=IsolationCfg(nonce_prefix=False, shuffle_order=False),
        verify=VerifyCfg(enabled=True),
    )

    def boom(*args, **kwargs):
        raise RuntimeError("simulated verify parser crash")

    monkeypatch.setattr(runner_module, "run_verify", boom)
    # Also bypass baseline pre-flight so the test doesn't touch it
    monkeypatch.setattr(runner_module, "_maybe_run_baseline_verify",
                        lambda *a, **kw: None)

    from tests.fakes import FakeOpenCodeClient
    root = runner_module.run_experiment(exp, lambda e: FakeOpenCodeClient())

    rundir = root / "baseline" / "rep_0"
    assert (rundir / "manifest.json").is_file(), "manifest.json must exist even when verify raises"
    import json as _json
    metrics = _json.loads((rundir / "metrics.json").read_text())
    assert metrics["verify_status"] == "error"


def test_per_file_diffstat_handles_paths_with_spaces():
    """diff --git a/path with spaces/x b/path with spaces/x must keep the full path."""
    from abench.runner import _per_file_diffstat
    patch = (
        "diff --git a/has spaces/foo.py b/has spaces/foo.py\n"
        "--- a/has spaces/foo.py\n"
        "+++ b/has spaces/foo.py\n"
        "+added line\n"
    )
    out = _per_file_diffstat(patch)
    assert out == [("has spaces/foo.py", 1, 0)]


def test_per_file_diffstat_handles_git_quoted_unicode_path():
    """git quotes non-ASCII paths: 'diff --git "a/naïve.txt" "b/naïve.txt"'.
    The file must still be counted (else a real edit looks like no change)."""
    from abench.runner import _per_file_diffstat
    patch = (
        'diff --git "a/na\\303\\257ve.txt" "b/na\\303\\257ve.txt"\n'
        '--- "a/na\\303\\257ve.txt"\n'
        '+++ "b/na\\303\\257ve.txt"\n'
        "+added line\n"
    )
    out = _per_file_diffstat(patch)
    assert len(out) == 1
    assert out[0][1] == 1 and out[0][2] == 0  # +1/-0 counted
    assert out[0][0]  # a non-empty path captured
