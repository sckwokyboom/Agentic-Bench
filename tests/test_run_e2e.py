"""End-to-end smoke test for `abench run` + `abench report`.

Drives a real ``opencode run`` subprocess via the CLI entry-point, then
verifies that all expected artifacts are written and metrics are sane.
Skipped automatically when opencode is not installed.
Wall-clock: ~30–90 s (free model cold-start + title generation).
"""
from __future__ import annotations

import json
import shutil
import textwrap
from pathlib import Path

import pytest

from abench.cli import main

pytestmark = pytest.mark.skipif(
    shutil.which("opencode") is None,
    reason="opencode not installed",
)


def _write_tree(tmp_path: Path) -> Path:
    """Create the fixture / reference / task tree; return path to exp.yaml."""
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    (fixture_dir / "note.txt").write_text("start\n")

    reference_dir = tmp_path / "reference"
    reference_dir.mkdir()
    (reference_dir / "note.txt").write_text("start\nDONE\n")

    (tmp_path / "task.md").write_text(
        "Append the line DONE to note.txt using the bash tool, then reply done.\n"
    )
    (tmp_path / "system.md").write_text(
        "You are a precise assistant. Use tools to make changes.\n"
    )

    exp_yaml = tmp_path / "exp.yaml"
    exp_yaml.write_text(
        textwrap.dedent("""\
            name: smoke
            fixture_path: ./fixture
            reference_path: ./reference
            task_prompt: ./task.md
            system_prompt: ./system.md
            model: opencode/deepseek-v4-flash-free
            repetitions: 1
            conditions:
              - name: baseline
                augmentation: null
            output_dir: ./runs
            timeout_s: 180
        """)
    )
    return exp_yaml


def test_abench_run_e2e(tmp_path: Path):
    exp_yaml = _write_tree(tmp_path)

    rc = main(["run", str(exp_yaml)])

    # ── Return code ──────────────────────────────────────────────────────────
    assert rc == 0, "CLI main() returned non-zero"

    # ── Artifact tree ────────────────────────────────────────────────────────
    # Each run now writes under a timestamped batch dir: runs/smoke/<batch>/...
    exp_root = tmp_path / "runs" / "smoke"
    batches = [p for p in exp_root.iterdir() if p.is_dir()]
    assert len(batches) == 1, f"expected exactly one batch dir, got {batches}"
    run_root = batches[0]
    rep_dir = run_root / "baseline" / "rep_0"

    for name in ("manifest.json", "events.jsonl", "trace.json",
                 "changes.patch", "metrics.json"):
        assert (rep_dir / name).exists(), f"missing artifact: {name}"

    # ── metrics.json content ─────────────────────────────────────────────────
    metrics = json.loads((rep_dir / "metrics.json").read_text())

    assert metrics.get("n_tool_calls", 0) >= 1, (
        f"expected at least 1 tool call; got {metrics.get('n_tool_calls')}"
    )
    assert metrics.get("finished") is True, (
        f"expected finished=True; got {metrics.get('finished')}"
    )
    assert metrics.get("interrupted_reason") is None, (
        f"expected interrupted_reason=None; got {metrics.get('interrupted_reason')}"
    )
    assert metrics.get("success") is None, (
        "success should be None (manual review only)"
    )

    # ── report outputs ───────────────────────────────────────────────────────
    assert (run_root / "summary.csv").exists(), "summary.csv not written"
    assert (run_root / "summary.md").exists(), "summary.md not written"
