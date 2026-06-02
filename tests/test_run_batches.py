# tests/test_run_batches.py
import re
from pathlib import Path

from abench.config import Condition, Experiment, MetricsCfg, OpenCodeCfg, VerifyCfg
from abench.runner import default_batch_id, run_experiment
from tests.fakes import FakeOpenCodeClient


def _experiment(tmp_path: Path) -> Experiment:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "a.py").write_text("def f():\n    ...\n")
    reference = tmp_path / "reference"
    reference.mkdir()
    return Experiment(
        name="exp1",
        fixture_path=fixture,
        reference_path=reference,
        task_prompt="Restore f().",
        system_prompt="Be careful.",
        model="fake/model",
        output_dir=tmp_path / "runs",
        repetitions=1,
        conditions=[Condition(name="baseline", augmentation=None)],
        opencode=OpenCodeCfg(),
        metrics=MetricsCfg(),
        verify=VerifyCfg(enabled=False),
    )


def test_explicit_batch_ids_do_not_overwrite(tmp_path):
    exp = _experiment(tmp_path)

    root1 = run_experiment(exp, lambda e: FakeOpenCodeClient(), batch_id="b1")
    root2 = run_experiment(exp, lambda e: FakeOpenCodeClient(), batch_id="b2")

    # Returned roots are the batch dirs.
    assert root1.name == "b1"
    assert root2.name == "b2"

    base = tmp_path / "runs" / "exp1"
    m1 = base / "b1" / "baseline" / "rep_0" / "metrics.json"
    m2 = base / "b2" / "baseline" / "rep_0" / "metrics.json"

    # Both trees exist independently — no clobbering.
    assert m1.exists()
    assert m2.exists()
    assert root1 == base / "b1"
    assert root2 == base / "b2"


def test_default_batch_id_shape():
    bid = default_batch_id()
    assert re.fullmatch(r"\d{8}-\d{6}", bid), bid
