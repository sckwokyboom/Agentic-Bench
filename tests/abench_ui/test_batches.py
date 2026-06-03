import json
from pathlib import Path

from abench_ui.runs import batch_runs_dir, list_batches


def _seed_run(runs_root: Path, batch: str | None, cond: str, rep: int) -> Path:
    """Seed <runs_root>/[<batch>/]<cond>/rep_N/metrics.json (+manifest)."""
    parts = [runs_root]
    if batch:
        parts.append(batch)
    parts += [cond, f"rep_{rep}"]
    rd = Path(*parts)
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "metrics.json").write_text(json.dumps({
        "success": True, "finished": True, "interrupted_reason": None,
    }))
    (rd / "manifest.json").write_text(json.dumps({"condition": cond, "rep": rep}))
    return rd


def test_list_batches_newest_first(tmp_path: Path):
    root = tmp_path / "runs" / "exp"
    _seed_run(root, "20260101-000000", "baseline", 0)
    _seed_run(root, "20260102-000000", "baseline", 0)

    batches = list_batches(root)
    ids = [b["id"] for b in batches]
    assert ids == ["20260102-000000", "20260101-000000"]
    for b in batches:
        assert b["total_runs"] == 1
        assert b["valid_runs"] == 1


def test_batch_runs_dir_resolves(tmp_path: Path):
    root = tmp_path / "runs" / "exp"
    _seed_run(root, "20260101-000000", "baseline", 0)
    _seed_run(root, "20260102-000000", "baseline", 0)

    # None / "" -> newest batch
    assert batch_runs_dir(root, None) == root / "20260102-000000"
    assert batch_runs_dir(root, "") == root / "20260102-000000"
    # explicit batch id
    assert batch_runs_dir(root, "20260101-000000") == root / "20260101-000000"
    # unknown batch -> None
    assert batch_runs_dir(root, "nope") is None


def test_legacy_flat_layout(tmp_path: Path):
    root = tmp_path / "runs" / "exp"
    _seed_run(root, None, "baseline", 0)  # flat: <root>/baseline/rep_0/metrics.json

    batches = list_batches(root)
    assert len(batches) == 1
    assert batches[0]["id"] == "legacy"
    assert batches[0]["total_runs"] == 1
    assert batches[0]["valid_runs"] == 1

    # "legacy" and None both resolve to the flat root
    assert batch_runs_dir(root, "legacy") == root
    assert batch_runs_dir(root, None) == root


def test_legacy_sorts_after_real_batches(tmp_path: Path):
    """A root that has a real batch dir is NOT legacy; pure-flat is legacy-only."""
    root = tmp_path / "runs" / "exp"
    _seed_run(root, "20260101-000000", "baseline", 0)
    batches = list_batches(root)
    assert [b["id"] for b in batches] == ["20260101-000000"]


def test_list_batches_empty(tmp_path: Path):
    root = tmp_path / "runs" / "exp"
    assert list_batches(root) == []
    assert batch_runs_dir(root, None) is None
    assert batch_runs_dir(root, "legacy") is None


def test_explicit_in_progress_batch_resolves_without_runs(tmp_path: Path):
    """A just-created batch dir (live run, before the first rep wrote artefacts —
    e.g. during baseline verify) must resolve so the runs endpoint returns []
    rather than 404. A genuinely-unknown id still resolves to None (→ 404)."""
    root = tmp_path / "runs" / "exp"
    inprog = root / "20260603-135405"
    inprog.mkdir(parents=True)
    (inprog / "experiment.resolved.yaml").write_text("name: exp\n")  # no cond/rep yet
    assert batch_runs_dir(root, "20260603-135405") == inprog
    assert batch_runs_dir(root, "nope-not-a-dir") is None
