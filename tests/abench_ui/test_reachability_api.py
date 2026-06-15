"""POST /api/validate/reachability — returns the verdict, never the key."""
import textwrap
from pathlib import Path

from fastapi.testclient import TestClient

from abench.reachability import ReachabilityResult
from abench_ui.server import create_app


def _scaffold(root: Path) -> None:
    d = root / "exp-r"
    (d / "prompts").mkdir(parents=True)
    (d / "prompts" / "task.md").write_text("t")
    (d / "prompts" / "system.md").write_text("s")
    (d / "original").mkdir(); (d / "original" / "a.py").write_text("x")
    (d / "stripped").mkdir(); (d / "stripped" / "a.py").write_text("x")
    (d / "experiment.yaml").write_text(textwrap.dedent("""\
        name: exp-r
        fixture_path: ./stripped
        reference_path: ./original
        task_prompt: ./prompts/task.md
        system_prompt: ./prompts/system.md
        model: deepseek/deepseek-chat
        repetitions: 1
        output_dir: ./runs
        conditions:
          - {name: baseline, augmentation: null}
        opencode:
          agent: abench
          sandbox: {mode: none}
          providers:
            - id: deepseek
              base_url: https://api.deepseek.com/v1
              models: [deepseek-chat]
              api_key_env: DEEPSEEK_API_KEY
        verify:
          enabled: false
    """))


def test_reachability_endpoint(tmp_path, monkeypatch):
    _scaffold(tmp_path)
    monkeypatch.setattr("abench.reachability.validate_reachability",
                        lambda *a, **k: ReachabilityResult(True, "ok", ""))
    client = TestClient(create_app(experiments_dir=tmp_path))
    resp = client.post("/api/validate/reachability", json={"experiment_name": "exp-r"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["reachable"] is True and body["reason"] == "ok"
    assert "key" not in body and "detail" in body
