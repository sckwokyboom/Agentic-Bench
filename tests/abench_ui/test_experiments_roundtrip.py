from pathlib import Path
from abench_ui.experiments import write_experiment, read_experiment


def _base_payload(root: Path, conditions):
    (root / "stripped").mkdir(parents=True, exist_ok=True)
    (root / "stripped" / "a.py").write_text("x")
    (root / "original").mkdir(parents=True, exist_ok=True)
    return {
        "name": "exp", "fixture_path": str(root / "stripped"),
        "reference_path": str(root / "original"), "task_prompt": "do it",
        "system_prompt": "be careful", "model": "opencode/m",
        "output_dir": str(root / "runs"), "repetitions": 1,
        "conditions": conditions,
    }


def test_text_kind_externalizes_and_inlines_back(tmp_path):
    payload = _base_payload(tmp_path, [
        {"name": "aug", "augmentation": "INLINE SLICE TEXT", "augmentation_kind": "text"},
    ])
    write_experiment(tmp_path, "exp", payload)
    assert (tmp_path / "exp" / "slices" / "aug.md").read_text() == "INLINE SLICE TEXT"
    out = read_experiment(tmp_path, "exp")
    cond = out["conditions"][0]
    assert cond["augmentation"] == "INLINE SLICE TEXT"   # inlined back
    assert cond["augmentation_kind"] == "text"


def test_file_kind_stores_path_verbatim_and_reads_path_back(tmp_path):
    slice_file = tmp_path / "external" / "slice.md"
    slice_file.parent.mkdir(parents=True)
    slice_file.write_text("FILE SLICE CONTENT")
    payload = _base_payload(tmp_path, [
        {"name": "aug", "augmentation": str(slice_file), "augmentation_kind": "file"},
    ])
    write_experiment(tmp_path, "exp", payload)
    # NOT externalized to slices/
    assert not (tmp_path / "exp" / "slices" / "aug.md").exists()
    out = read_experiment(tmp_path, "exp", raw_file_aug=True)
    cond = out["conditions"][0]
    assert cond["augmentation"] == str(slice_file)       # path, not content
    assert cond["augmentation_kind"] == "file"


def test_file_kind_default_read_inlines_content_for_run(tmp_path):
    slice_file = tmp_path / "external" / "slice.md"
    slice_file.parent.mkdir(parents=True)
    slice_file.write_text("FILE SLICE CONTENT")
    payload = _base_payload(tmp_path, [
        {"name": "aug", "augmentation": str(slice_file), "augmentation_kind": "file"},
    ])
    write_experiment(tmp_path, "exp", payload)
    # Default read (RUN / recompute path) must inline the file's CONTENT so the
    # runner injects the text, not the path string.
    out = read_experiment(tmp_path, "exp")
    assert out["conditions"][0]["augmentation"] == "FILE SLICE CONTENT"


def test_mixed_text_and_file_conditions(tmp_path):
    slice_file = tmp_path / "external" / "graph.md"
    slice_file.parent.mkdir(parents=True)
    slice_file.write_text("FILE CONTENT")
    payload = _base_payload(tmp_path, [
        {"name": "inline", "augmentation": "INLINE TEXT", "augmentation_kind": "text"},
        {"name": "fromfile", "augmentation": str(slice_file), "augmentation_kind": "file"},
    ])
    write_experiment(tmp_path, "exp", payload)
    assert (tmp_path / "exp" / "slices" / "inline.md").read_text() == "INLINE TEXT"
    assert not (tmp_path / "exp" / "slices" / "fromfile.md").exists()
    # Editor view: text inlined, file shows its path.
    ed = read_experiment(tmp_path, "exp", raw_file_aug=True)
    by = {c["name"]: c for c in ed["conditions"]}
    assert by["inline"]["augmentation"] == "INLINE TEXT"
    assert by["fromfile"]["augmentation"] == str(slice_file)
    # Run view: both inlined to content.
    run = read_experiment(tmp_path, "exp")
    by2 = {c["name"]: c for c in run["conditions"]}
    assert by2["inline"]["augmentation"] == "INLINE TEXT"
    assert by2["fromfile"]["augmentation"] == "FILE CONTENT"


def test_duplicate_condition_names_rejected(tmp_path):
    import pytest
    from abench.config import load_experiment
    payload = _base_payload(tmp_path, [
        {"name": "dup", "augmentation": None},
        {"name": "dup", "augmentation": None},
    ])
    write_experiment(tmp_path, "exp", payload)
    with pytest.raises(ValueError, match="duplicate condition name"):
        load_experiment(tmp_path / "exp" / "experiment.yaml")
