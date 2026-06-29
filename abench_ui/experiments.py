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


def read_experiment(root: Path, name: str, *, raw_file_aug: bool = False) -> dict:
    """Return the Experiment payload.

    `load_experiment` inlines every augmentation to its resolved TEXT (reading
    the file for a file-kind path), which is what the RUN / recompute paths
    need — the augmentation text is injected into the prompt. The EDITOR,
    however, needs to show a file-kind condition's PATH (the file binding), not
    the inlined blob: pass ``raw_file_aug=True`` and the pre-resolution path is
    restored from the raw YAML for file-kind conditions. Text-kind conditions
    are always inlined.
    """
    yaml_path = Path(root) / name / "experiment.yaml"
    if not yaml_path.is_file():
        raise ExperimentNotFound(name)
    exp = load_experiment(yaml_path)
    data = exp.model_dump(mode="json")
    if raw_file_aug:
        raw = yaml.safe_load(yaml_path.read_text()) or {}
        raw_by_name = {c.get("name"): c for c in raw.get("conditions", [])
                       if isinstance(c, dict)}
        for cond in data.get("conditions", []):
            if cond.get("augmentation_kind") == "file":
                rc = raw_by_name.get(cond.get("name"))
                if rc is not None:
                    cond["augmentation"] = rc.get("augmentation")
    return data


_PROMPTS_DIR = "prompts"
_SLICES_DIR = "slices"


def write_experiment(root: Path, name: str, payload: dict) -> None:
    """Write the payload back atomically.

    - system_prompt → prompts/system.md
    - task_prompt   → prompts/task.md
    - condition.augmentation (if not None) → slices/<condition>.md
    - condition.system_augmentation (if not None) → slices/<condition>-system.md
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

    # NOTE: mutates the caller's condition dicts in place (text-kind augmentation
    # is rewritten to its slices/<name>.md path; file-kind is left untouched).
    for cond in conditions:
        aug = cond.get("augmentation")
        # File-kind augmentation is a path the user manages → store verbatim, do
        # NOT externalize. Text-kind is inline markdown → slices/<name>.md.
        if aug is not None and cond.get("augmentation_kind") != "file":
            slice_path = f"./{_SLICES_DIR}/{cond['name']}.md"
            _atomic_write(exp_dir / _SLICES_DIR / f"{cond['name']}.md", aug)
            cond["augmentation"] = slice_path
        # Externalise the per-condition system-prompt augmentation too, so it is
        # stored as a .md ref rather than inlined into the YAML (an inlined
        # multi-line blob would then be (mis)read back as a filesystem path).
        sys_aug = cond.get("system_augmentation")
        if sys_aug is not None:
            sys_path = f"./{_SLICES_DIR}/{cond['name']}-system.md"
            _atomic_write(exp_dir / _SLICES_DIR / f"{cond['name']}-system.md", sys_aug)
            cond["system_augmentation"] = sys_path

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
    p = Path(target)
    if not p.is_absolute():
        # A relative path (e.g. from an uploaded yaml — the server never saw the
        # file's original directory) is interpreted relative to the experiment
        # dir on read. Keep it relative; resolving it here would resolve against
        # the server CWD (the project root), producing a bogus absolute path.
        return target if target.startswith(("./", "../")) else f"./{target}"
    try:
        return "./" + str(p.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(p.resolve())
