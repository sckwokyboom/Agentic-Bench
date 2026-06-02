import json
from pathlib import Path

from fastapi.testclient import TestClient

from abench_ui.server import create_app


def _seed(exp_dir: Path, name: str, condition: str, rep: int):
    d = exp_dir / name / "runs" / name / condition / f"rep_{rep}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "verify_output.log").write_text("# command: mvn test\n───\nBUILD FAILURE\n")


def test_verify_log_served(tmp_path: Path):
    exp_dir = tmp_path / "experiments"
    _seed(exp_dir, "exp", "baseline", 0)
    client = TestClient(create_app(experiments_dir=exp_dir))
    resp = client.get("/api/runs/exp/baseline/0/verify_log")
    assert resp.status_code == 200
    assert "BUILD FAILURE" in resp.text


def test_verify_log_404_when_absent(tmp_path: Path):
    exp_dir = tmp_path / "experiments"
    (exp_dir / "exp" / "runs" / "exp" / "baseline" / "rep_0").mkdir(parents=True)
    client = TestClient(create_app(experiments_dir=exp_dir))
    resp = client.get("/api/runs/exp/baseline/0/verify_log")
    assert resp.status_code == 404


def test_detect_verify_command_maven(tmp_path: Path):
    exp_dir = tmp_path / "experiments"
    d = exp_dir / "exp"
    (d / "stripped").mkdir(parents=True)
    (d / "stripped" / "pom.xml").write_text("<project/>")
    (d / "reference").mkdir()
    (d / "reference" / "pom.xml").write_text("<project/>")
    (d / "prompts").mkdir()
    (d / "prompts" / "task.md").write_text("do it")
    (d / "prompts" / "system.md").write_text("sys")
    (d / "experiment.yaml").write_text(
        "name: exp\nfixture_path: ./stripped\nreference_path: ./reference\n"
        "task_prompt: ./prompts/task.md\nsystem_prompt: ./prompts/system.md\n"
        "model: m\nrepetitions: 1\noutput_dir: ./runs\n"
        "conditions:\n  - {name: baseline, augmentation: null}\n"
    )
    client = TestClient(create_app(experiments_dir=exp_dir))
    resp = client.get("/api/experiments/exp/verify_command")
    assert resp.status_code == 200
    body = resp.json()
    assert body["system"] == "maven"
    assert body["command"] == "mvn test"


def test_detect_verify_command_404_when_no_experiment(tmp_path: Path):
    exp_dir = tmp_path / "experiments"
    (exp_dir / "exp").mkdir(parents=True)
    client = TestClient(create_app(experiments_dir=exp_dir))
    resp = client.get("/api/experiments/exp/verify_command")
    assert resp.status_code == 404


def test_verify_command_endpoint_reports_ambiguity(tmp_path):
    from fastapi.testclient import TestClient
    from abench_ui.server import create_app
    exp_dir = tmp_path / "experiments"; d = exp_dir / "exp"
    (d / "fix").mkdir(parents=True)
    (d / "fix" / "build.gradle").write_text("")
    (d / "fix" / "gradlew").write_text("")
    (d / "fix" / "pom.xml").write_text("<project/>")
    (d / "ref").mkdir(); (d / "prompts").mkdir()
    (d / "prompts" / "task.md").write_text("t"); (d / "prompts" / "system.md").write_text("s")
    (d / "experiment.yaml").write_text(
        "name: exp\nfixture_path: ./fix\nreference_path: ./ref\n"
        "task_prompt: ./prompts/task.md\nsystem_prompt: ./prompts/system.md\n"
        "model: m\nrepetitions: 1\noutput_dir: ./runs\n"
        "conditions:\n  - {name: baseline, augmentation: null}\n")
    client = TestClient(create_app(experiments_dir=exp_dir))
    body = client.get("/api/experiments/exp/verify_command").json()
    assert body["system"] == "gradle" and body["command"] == "./gradlew test"
    assert body["ambiguous"] is True and set(body["candidates"]) == {"gradle", "maven"}
