"""CRUD on experiments/<name>/ directories.

The on-disk layout is the source of truth. Reads return a fully-resolved payload
(prompt and slice text inlined). Writes split the payload back to YAML +
prompts/*.md + slices/*.md, with temp+rename for atomicity.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml

from abench.config import load_experiment


class ExperimentNotFound(Exception):
    pass


def list_experiments(root: Path) -> list[dict]:
    """Return [{name, has_fixture, has_reference, has_runs, last_run_at}]."""
    root = Path(root)
    if not root.is_dir():
        return []
    items: list[dict] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        yaml_path = entry / "experiment.yaml"
        if not yaml_path.is_file():
            continue
        items.append({
            "name": entry.name,
            "has_fixture": (entry / "stripped").is_dir(),
            "has_reference": (entry / "original").is_dir(),
            "has_runs": (entry / "runs").is_dir() and any(
                (entry / "runs").iterdir()),
            "last_run_at": _last_run_at(entry / "runs"),
        })
    return items


def _last_run_at(runs_dir: Path) -> str | None:
    if not runs_dir.is_dir():
        return None
    candidates = list(runs_dir.glob("*/*/*/manifest.json"))
    if not candidates:
        return None
    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    import datetime
    return datetime.datetime.fromtimestamp(latest.stat().st_mtime).isoformat()


def read_experiment(root: Path, name: str) -> dict:
    """Return the fully-resolved Experiment payload (texts inlined)."""
    yaml_path = Path(root) / name / "experiment.yaml"
    if not yaml_path.is_file():
        raise ExperimentNotFound(name)
    exp = load_experiment(yaml_path)
    # model_dump returns paths as Path objects; serialise to str
    data = exp.model_dump(mode="json")
    return data


_PROMPTS_DIR = "prompts"
_SLICES_DIR = "slices"


def write_experiment(root: Path, name: str, payload: dict) -> None:
    """Write the payload back atomically.

    - system_prompt → prompts/system.md
    - task_prompt   → prompts/task.md
    - condition.augmentation (if not None) → slices/<condition>.md
    - everything else → experiment.yaml (with paths replaced by relative .md refs)
    """
    exp_dir = Path(root) / name
    exp_dir.mkdir(parents=True, exist_ok=True)
    (exp_dir / _PROMPTS_DIR).mkdir(exist_ok=True)
    (exp_dir / _SLICES_DIR).mkdir(exist_ok=True)

    # Pull text fields out
    yaml_payload = dict(payload)
    system_text = yaml_payload.pop("system_prompt", "")
    task_text = yaml_payload.pop("task_prompt", "")
    conditions = yaml_payload.get("conditions", [])

    _atomic_write(exp_dir / _PROMPTS_DIR / "system.md", system_text)
    _atomic_write(exp_dir / _PROMPTS_DIR / "task.md", task_text)

    # Replace text fields with relative paths in the yaml payload
    yaml_payload["system_prompt"] = f"./{_PROMPTS_DIR}/system.md"
    yaml_payload["task_prompt"] = f"./{_PROMPTS_DIR}/task.md"

    for cond in conditions:
        aug = cond.get("augmentation")
        if aug is None:
            continue
        slice_path = f"./{_SLICES_DIR}/{cond['name']}.md"
        _atomic_write(exp_dir / _SLICES_DIR / f"{cond['name']}.md", aug)
        cond["augmentation"] = slice_path

    # Make path fields relative if they live under exp_dir, else absolute
    for key in ("fixture_path", "reference_path", "output_dir"):
        if key in yaml_payload and yaml_payload[key]:
            yaml_payload[key] = _relpath(yaml_payload[key], exp_dir)

    _atomic_write(exp_dir / "experiment.yaml",
                  yaml.safe_dump(yaml_payload, sort_keys=False, allow_unicode=True))


def _atomic_write(path: Path, text: str) -> None:
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _relpath(target: str, base: Path) -> str:
    target_p = Path(target).resolve()
    try:
        return "./" + str(target_p.relative_to(base.resolve()))
    except ValueError:
        return str(target_p)
