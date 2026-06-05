"""POST /api/runs/{name}/recompute — offline metric recompute for a batch."""
import json
import textwrap
from pathlib import Path

from fastapi.testclient import TestClient

from abench.trace_model import Trace, TurnInfo
from abench_ui.server import create_app


def _scaffold(root: Path) -> None:
    d = root / "exp-rc"
    (d / "prompts").mkdir(parents=True)
    (d / "prompts" / "task.md").write_text("t")
    (d / "prompts" / "system.md").write_text("s")
    (d / "original").mkdir()
    (d / "original" / "a.py").write_text("x")
    (d / "stripped").mkdir()
    (d / "stripped" / "a.py").write_text("x")
    (d / "experiment.yaml").write_text(textwrap.dedent("""\
        name: exp-rc
        fixture_path: ./stripped
        reference_path: ./original
        task_prompt: ./prompts/task.md
        system_prompt: ./prompts/system.md
        model: m
        repetitions: 1
        output_dir: ./runs
        conditions:
          - {name: baseline, augmentation: null}
        verify: {enabled: false}
        isolation: {nonce_prefix: false, shuffle_order: false}
    """))


def test_recompute_endpoint_backfills_tokens(tmp_path):
    _scaffold(tmp_path)
    rd = (tmp_path / "exp-rc" / "runs" / "exp-rc" / "20260101-000000"
          / "baseline" / "rep_0")
    rd.mkdir(parents=True)
    # A finished run whose trace has per-turn tokens but no totals (export gave
    # nothing) — exactly the case that left the table blank.
    tr = Trace(turns=[TurnInfo(message_id="M0", tokens_in=120, tokens_out=30)],
               tokens_in=None, tokens_out=None)
    (rd / "trace.json").write_text(json.dumps(tr.to_dict()))
    (rd / "changes.patch").write_text("")
    (rd / "metrics.json").write_text(json.dumps({"tokens_in": None}))
    (rd / "manifest.json").write_text(json.dumps({"condition": "baseline", "rep": 0}))

    c = TestClient(create_app(experiments_dir=tmp_path))
    r = c.post("/api/runs/exp-rc/recompute?batch=20260101-000000")
    assert r.status_code == 200
    assert r.json()["recomputed"] == 1
    m = json.loads((rd / "metrics.json").read_text())
    assert m["tokens_in"] == 120 and m["tokens_out"] == 30


def test_recompute_endpoint_unknown_experiment_404(tmp_path):
    c = TestClient(create_app(experiments_dir=tmp_path))
    assert c.post("/api/runs/nope/recompute").status_code == 404
