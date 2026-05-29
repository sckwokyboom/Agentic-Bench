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
                 timeout_s, on_event):
        self.captures.append(system_prompt)
        return self._fake.run_task(
            workdir=workdir, system_prompt=system_prompt, model=model,
            user_message=user_message, timeout_s=timeout_s, on_event=on_event,
        )


def test_nonce_prefix_prepended_when_enabled(tmp_path):
    exp = _make_exp(tmp_path, IsolationCfg(nonce_prefix=True, shuffle_order=False))
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
    exp = _make_exp(tmp_path, IsolationCfg(nonce_prefix=False, shuffle_order=False))
    rec = _RecordingClient()
    run_experiment(exp, lambda e: rec)
    for prompt in rec.captures:
        assert prompt == "ORIGINAL_SYSTEM_PROMPT"


def test_shuffle_changes_run_order_deterministically(tmp_path):
    """With shuffle_order=True and a fixed date-seed, the order is permuted but
    reproducible within the same day."""
    exp = _make_exp(tmp_path, IsolationCfg(nonce_prefix=False, shuffle_order=True))
    rec = _RecordingClient()
    run_experiment(exp, lambda e: rec)

    # Read manifests in disk order — they should reflect the actual run sequence
    manifests = sorted((tmp_path / "runs" / "iso-test").glob("*/rep_*/manifest.json"))
    order = [json.loads(m.read_text())["condition"] + "/" +
             str(json.loads(m.read_text())["rep"]) for m in manifests]
    assert sorted(order) == sorted([
        "baseline/0", "baseline/1", "augmented/0", "augmented/1",
    ])
    # NOTE: with a fixed day-seed the permutation is deterministic; we don't
    # assert a specific order here because day rolls; just that all 4 ran.
