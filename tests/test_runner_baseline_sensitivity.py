"""Baseline sensitivity (A3): verify the STRIPPED fixture in addition to the
reference, so pass/fail that cannot reflect agent work is flagged
(``verify_insensitive``)."""
import json
from pathlib import Path
from unittest import mock

from abench.config import Condition, Experiment, IsolationCfg, MetricsCfg, OpenCodeCfg, VerifyCfg
from abench import runner as runner_module
from abench.runner import run_experiment, _maybe_run_baseline_verify
from abench.verify import VerifyResult
from tests.fakes import FakeOpenCodeClient


def _make_exp(tmp_path: Path) -> Experiment:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "a.py").write_text("x = 1\n")
    reference = tmp_path / "reference"
    reference.mkdir()
    (reference / "a.py").write_text("x = 1\n")
    return Experiment(
        name="sens",
        fixture_path=fixture,
        reference_path=reference,
        task_prompt="t",
        system_prompt="s",
        model="fake/m",
        output_dir=tmp_path / "runs",
        repetitions=1,
        conditions=[Condition(name="baseline", augmentation=None)],
        opencode=OpenCodeCfg(),
        metrics=MetricsCfg(),
        isolation=IsolationCfg(nonce_prefix=False, shuffle_order=False),
        verify=VerifyCfg(enabled=True, command="pytest"),
    )


def _passed():
    return VerifyResult(status="passed", reason="passed", message="ok", command="pytest",
                        passed_count=1, failed_count=0)


def _failed():
    return VerifyResult(status="failed", reason="tests_failed", message="boom",
                        command="pytest", passed_count=0, failed_count=1)


def test_baseline_cache_records_reference_and_fixture(tmp_path):
    exp = _make_exp(tmp_path)
    cache = exp.fixture_path.parent / ".verify-baseline.json"
    with mock.patch.object(runner_module, "run_verify", return_value=_passed()):
        _maybe_run_baseline_verify(exp, cache)
    data = json.loads(cache.read_text())
    # Back-compat keys
    assert data["status"] == "passed"
    assert "reference_sha" in data
    # New keys
    assert data["fixture_status"] == "passed"
    assert "fixture_sha" in data


def test_verify_insensitive_true_when_fixture_passes(tmp_path):
    exp = _make_exp(tmp_path)
    # Both reference (baseline pre-flight) and fixture (post-run) verify → passed.
    with mock.patch.object(runner_module, "run_verify", return_value=_passed()):
        root = run_experiment(exp, lambda e: FakeOpenCodeClient())
    rundir = root / "baseline" / "rep_0"
    trace = json.loads((rundir / "trace.json").read_text())
    metrics = json.loads((rundir / "metrics.json").read_text())
    assert trace["verify_insensitive"] is True
    assert metrics["verify_insensitive"] is True


def test_verify_insensitive_false_when_fixture_fails(tmp_path):
    exp = _make_exp(tmp_path)

    # Reference verify (baseline pre-flight) on a copy of reference_path passes,
    # but the stripped fixture fails. Discriminate by which workdir is verified.
    def fake_verify(workdir, command, timeout_s, on_line=None):
        # The fixture copy contains a.py == "x = 1"; reference is identical here,
        # so distinguish by path: baseline pre-flight verifies reference_path's
        # copy, fixture pre-flight verifies fixture_path's copy. We instead key
        # on call order via a counter.
        return _failed() if fake_verify.calls.pop(0) == "fixture" else _passed()

    # Order in _maybe_run_baseline_verify: reference first, then fixture.
    # Then the per-run verify in _run_one runs once more (we don't care about it
    # for insensitivity — that flag comes from the cached fixture_status).
    fake_verify.calls = ["reference", "fixture", "run"]

    with mock.patch.object(runner_module, "run_verify", side_effect=fake_verify):
        root = run_experiment(exp, lambda e: FakeOpenCodeClient())
    cache = exp.fixture_path.parent / ".verify-baseline.json"
    data = json.loads(cache.read_text())
    assert data["status"] == "passed"
    assert data["fixture_status"] == "failed"
    rundir = root / "baseline" / "rep_0"
    trace = json.loads((rundir / "trace.json").read_text())
    assert trace["verify_insensitive"] is False


def test_baseline_verify_emits_subphases(tmp_path):
    """emit receives a baseline_verify sub-phase per side (N/M) with the cache hint,
    instead of one static line for the whole multi-minute window."""
    exp = _make_exp(tmp_path)
    cache = exp.fixture_path.parent / ".verify-baseline.json"
    emitted = []
    with mock.patch.object(runner_module, "run_verify", return_value=_passed()):
        _maybe_run_baseline_verify(exp, cache, emit=emitted.append)
    msgs = [e["message"] for e in emitted if e.get("phase") == "baseline_verify"]
    assert any("1/2" in m for m in msgs)      # reference side
    assert any("2/2" in m for m in msgs)      # stripped fixture side
    assert any("cached in .verify-baseline.json" in m for m in msgs)
