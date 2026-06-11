# tests/test_cli_lib.py
import json

from abench.cli import main


def test_lib_add_then_list(tmp_path, monkeypatch, capsys):
    reg = tmp_path / ".abench.local.json"
    monkeypatch.setenv("ABENCH_LOCAL_CONFIG", str(reg))
    assert main(["lib", "add", "graph-tipper", "/opt/gt"]) == 0
    assert json.loads(reg.read_text())["libraries"]["graph-tipper"] == "/opt/gt"
    assert main(["lib", "list"]) == 0
    assert "graph-tipper" in capsys.readouterr().out
