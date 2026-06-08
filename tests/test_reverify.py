import json
from pathlib import Path
from unittest import mock

from abench import reverify
from abench.verify import VerifyResult


def _make_exp(tmp_path: Path):
    from abench.config import Experiment
    fixture = tmp_path / "fix"
    fixture.mkdir()
    (fixture / "a.txt").write_text("old\n")
    runs = tmp_path / "runs"
    exp = Experiment(
        name="exp", fixture_path=fixture, reference_path=fixture,
        task_prompt="t", system_prompt="s", model="m", repetitions=1,
        output_dir=runs, conditions=[{"name": "baseline", "augmentation": None}],
    )
    return exp, fixture, runs


def _seed_run(runs: Path, condition: str, rep: int, patch: str):
    rd = runs / "exp" / condition / f"rep_{rep}"
    rd.mkdir(parents=True)
    (rd / "changes.patch").write_text(patch)
    (rd / "metrics.json").write_text(json.dumps({"verify_status": "error", "success": None}))
    (rd / "trace.json").write_text(json.dumps({"steps": [], "turns": []}))
    return rd


def _seed_batched_run(runs: Path, batch: str, condition: str, rep: int, patch: str):
    """Seed a TIMESTAMPED-BATCH run at runs/exp/<batch>/<cond>/rep_N/."""
    rd = runs / "exp" / batch / condition / f"rep_{rep}"
    rd.mkdir(parents=True)
    (rd / "changes.patch").write_text(patch)
    (rd / "metrics.json").write_text(json.dumps({"verify_status": "error", "success": None}))
    (rd / "trace.json").write_text(json.dumps({"steps": [], "turns": []}))
    return rd


_GOOD_PATCH = (
    "diff --git a/a.txt b/a.txt\n"
    "--- a/a.txt\n+++ b/a.txt\n"
    "@@ -1 +1 @@\n-old\n+new\n"
)


def test_reverify_run_happy_writes_back(tmp_path):
    exp, _fix, runs = _make_exp(tmp_path)
    rd = _seed_run(runs, "baseline", 0, _GOOD_PATCH)
    fake = VerifyResult(status="passed", reason="passed", message="5 tests passed",
                        command="pytest", duration_s=1.2, passed_count=5, failed_count=0,
                        raw_output="5 passed in 1.2s\n")
    with mock.patch("abench.reverify.run_verify", return_value=fake), \
         mock.patch("abench.reverify.detect_command", return_value="pytest"):
        v = reverify.reverify_run(exp, "baseline", 0)
    assert v.status == "passed"
    m = json.loads((rd / "metrics.json").read_text())
    assert m["verify_status"] == "passed"
    assert m["verify_reason"] == "passed"
    assert m["success"] is True
    tr = json.loads((rd / "trace.json").read_text())
    assert tr["verify_message"] == "5 tests passed"
    assert "5 passed" in (rd / "verify_output.log").read_text()


def test_reverify_augments_command_and_writes_expected_total(tmp_path):
    """Re-verify re-runs with --continue (full suite, not the truncated count the
    run aborted at) and records the reference's full size as verify_expected_total
    so a later recompute scores tests_pass_rate against the whole suite."""
    exp, fix, runs = _make_exp(tmp_path)
    (fix.parent / ".verify-baseline.json").write_text(
        json.dumps({"status": "passed", "passed_count": 2437}))
    rd = _seed_run(runs, "baseline", 0, _GOOD_PATCH)
    captured = {}

    def fake_run_verify(workdir, command, timeout_s):
        captured["command"] = command
        return VerifyResult(status="failed", reason="tests_failed",
                            message="1 of 2281 failed", command=command,
                            passed_count=2280, failed_count=1)

    with mock.patch("abench.reverify.run_verify", side_effect=fake_run_verify), \
         mock.patch("abench.reverify.detect_command", return_value="./gradlew test"):
        reverify.reverify_run(exp, "baseline", 0)

    assert captured["command"] == "./gradlew test --continue"
    tr = json.loads((rd / "trace.json").read_text())
    assert tr["verify_expected_total"] == 2437
    assert json.loads((rd / "metrics.json").read_text())["verify_expected_total"] == 2437


def test_reverify_run_patch_apply_failed(tmp_path):
    exp, _fix, runs = _make_exp(tmp_path)
    rd = _seed_run(runs, "baseline", 0, "diff --git a/a.txt b/a.txt\n@@ bogus @@\nnonsense\n")
    v = reverify.reverify_run(exp, "baseline", 0)
    assert v.status == "error"
    assert v.reason == "patch_apply_failed"
    m = json.loads((rd / "metrics.json").read_text())
    assert m["verify_reason"] == "patch_apply_failed"
    assert m["success"] is None


def test_reverify_run_no_run(tmp_path):
    exp, _fix, _runs = _make_exp(tmp_path)
    v = reverify.reverify_run(exp, "baseline", 0)
    assert v.status == "error" and v.reason == "no_run"


def test_discover_and_reverify_experiment(tmp_path):
    exp, _fix, runs = _make_exp(tmp_path)
    _seed_run(runs, "baseline", 0, _GOOD_PATCH)
    _seed_run(runs, "augmented", 0, _GOOD_PATCH)
    assert sorted(reverify.discover_runs(exp)) == [("augmented", 0), ("baseline", 0)]
    fake = VerifyResult(status="passed", reason="passed", message="ok", command="pytest")
    with mock.patch("abench.reverify.run_verify", return_value=fake), \
         mock.patch("abench.reverify.detect_command", return_value="pytest"):
        results = list(reverify.reverify_experiment(exp))
    assert len(results) == 2
    assert all(v.status == "passed" for _c, _r, v in results)


# ── batch-aware re-verify (timestamped-batch layout is now the default) ───────

_BATCH = "20260101-000000"


def test_discover_runs_finds_batched_run_by_explicit_id(tmp_path):
    exp, _fix, runs = _make_exp(tmp_path)
    _seed_batched_run(runs, _BATCH, "baseline", 0, _GOOD_PATCH)
    assert reverify.discover_runs(exp, batch=_BATCH) == [("baseline", 0)]


def test_discover_runs_default_resolves_newest_batch(tmp_path):
    exp, _fix, runs = _make_exp(tmp_path)
    _seed_batched_run(runs, "20260101-000000", "baseline", 0, _GOOD_PATCH)
    _seed_batched_run(runs, "20260102-000000", "augmented", 0, _GOOD_PATCH)
    # No batch → newest batch only.
    assert reverify.discover_runs(exp) == [("augmented", 0)]


def test_discover_runs_default_resolves_legacy_flat(tmp_path):
    exp, _fix, runs = _make_exp(tmp_path)
    _seed_run(runs, "baseline", 0, _GOOD_PATCH)  # flat / legacy layout
    assert reverify.discover_runs(exp) == [("baseline", 0)]


def test_reverify_run_resolves_batched_rundir_and_writes_back(tmp_path):
    exp, _fix, runs = _make_exp(tmp_path)
    rd = _seed_batched_run(runs, _BATCH, "baseline", 0, _GOOD_PATCH)
    fake = VerifyResult(status="passed", reason="passed", message="5 tests passed",
                        command="pytest", duration_s=1.2, passed_count=5, failed_count=0,
                        raw_output="5 passed in 1.2s\n")
    with mock.patch("abench.reverify.run_verify", return_value=fake), \
         mock.patch("abench.reverify.detect_command", return_value="pytest"):
        v = reverify.reverify_run(exp, "baseline", 0, batch=_BATCH)
    assert v.status == "passed"
    m = json.loads((rd / "metrics.json").read_text())
    assert m["verify_status"] == "passed"
    assert m["success"] is True
    tr = json.loads((rd / "trace.json").read_text())
    assert tr["verify_message"] == "5 tests passed"
    assert "5 passed" in (rd / "verify_output.log").read_text()


def test_reverify_run_default_batch_writes_to_newest(tmp_path):
    exp, _fix, runs = _make_exp(tmp_path)
    rd = _seed_batched_run(runs, _BATCH, "baseline", 0, _GOOD_PATCH)
    fake = VerifyResult(status="passed", reason="passed", message="ok", command="pytest")
    with mock.patch("abench.reverify.run_verify", return_value=fake), \
         mock.patch("abench.reverify.detect_command", return_value="pytest"):
        v = reverify.reverify_run(exp, "baseline", 0)
    assert v.status == "passed"
    m = json.loads((rd / "metrics.json").read_text())
    assert m["verify_status"] == "passed"


def test_reverify_run_no_run_when_batch_missing(tmp_path):
    exp, _fix, _runs = _make_exp(tmp_path)
    v = reverify.reverify_run(exp, "baseline", 0, batch="nope")
    assert v.status == "error" and v.reason == "no_run"


def test_reverify_experiment_batched(tmp_path):
    exp, _fix, runs = _make_exp(tmp_path)
    _seed_batched_run(runs, _BATCH, "baseline", 0, _GOOD_PATCH)
    _seed_batched_run(runs, _BATCH, "augmented", 0, _GOOD_PATCH)
    fake = VerifyResult(status="passed", reason="passed", message="ok", command="pytest")
    with mock.patch("abench.reverify.run_verify", return_value=fake), \
         mock.patch("abench.reverify.detect_command", return_value="pytest"):
        results = list(reverify.reverify_experiment(exp, batch=_BATCH))
    assert len(results) == 2
    assert all(v.status == "passed" for _c, _r, v in results)
