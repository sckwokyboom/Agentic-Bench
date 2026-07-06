"""Multi-SWE-bench native-format helpers (schema accessors; evaluator driver +
report reader come in later Plan-4b tasks). Pinned harness:
github.com/multi-swe-bench/multi-swe-bench @ 24f493f8 (v1.1.0)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def instance_id(rec: dict) -> str:
    """The harness's id: 'org/repo:pr-<number>'."""
    return f"{rec['org']}/{rec['repo']}:pr-{rec['number']}"


def display_repo(rec: dict) -> str:
    return f"{rec['org']}/{rec['repo']}"


def base_sha(rec: dict) -> str:
    return rec["base"]["sha"]


def image_ref(rec: dict) -> str:
    """Official per-PR image: mswebench/<org>_m_<repo>:pr-<number> (lowercased)."""
    return f"mswebench/{rec['org']}_m_{rec['repo']}:pr-{rec['number']}".lower()


def issue_text(rec: dict) -> str:
    """Canonical issue text: title + body + linked resolved-issue bodies. No gold,
    no tests, no hints (issue-only fidelity, spec §2)."""
    parts: list[str] = []
    if rec.get("title"):
        parts.append(rec["title"].strip())
    if rec.get("body"):
        parts.append(rec["body"].strip())
    for iss in rec.get("resolved_issues") or []:
        t, b = (iss.get("title") or "").strip(), (iss.get("body") or "").strip()
        if t or b:
            parts.append((t + "\n" + b).strip())
    return "\n\n".join(p for p in parts if p)


def prediction_record(rec: dict, fix_patch: str) -> dict[str, Any]:
    """The evaluator's prediction JSONL record — {org, repo, number, fix_patch} ONLY."""
    return {"org": rec["org"], "repo": rec["repo"], "number": rec["number"], "fix_patch": fix_patch}


def _docker_cp_repo(image: str, src: str, dest: str) -> None:
    """Extract `src` (a directory inside `image`, e.g. /home/<repo>) into `dest` on
    the host, via a throwaway container: docker create → docker cp → docker rm.
    `dest` receives the CONTENTS of `src` (the trailing `/.`). Raises a clear error
    if the image is not present locally. Isolated so tests can monkeypatch it (the
    real call needs Docker + the pulled official image)."""
    try:
        created = subprocess.run(
            ["docker", "create", image],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"`docker create {image}` failed — is the image pulled locally and is the "
            f"Docker daemon running? Pre-pull with "
            f"`bash scripts/download_images.sh scripts/images_verified.txt`. "
            f"stderr: {e.stderr}"
        ) from e
    cid = created.stdout.strip()
    try:
        subprocess.run(
            ["docker", "cp", f"{cid}:{src}/.", dest],
            check=True, capture_output=True, text=True,
        )
    finally:
        subprocess.run(["docker", "rm", "-f", cid], capture_output=True, text=True)


def run_evaluation(msb_root: str, config: dict, output_dir: str) -> dict:
    """Run the official multi-swe-bench evaluator on a prepared config and return the
    parsed final_report.json. Writes config.json into output_dir, runs
    `python -m multi_swe_bench.harness.run_evaluation --config <cfg>` with
    cwd=msb_root (the pinned checkout), reads output_dir/final_report.json.
    Isolated so tests monkeypatch it (the real call needs Docker + the harness
    installed in this interpreter). HOST(Task 5): confirm the harness is importable
    via `sys.executable -m multi_swe_bench.harness.run_evaluation` (pip install -e)."""
    cfg_path = Path(output_dir) / "config.json"
    cfg_path.write_text(json.dumps(config))
    subprocess.run(
        [sys.executable, "-m", "multi_swe_bench.harness.run_evaluation",
         "--config", str(cfg_path)],
        cwd=msb_root, check=True,
    )
    return json.loads((Path(output_dir) / "final_report.json").read_text())
