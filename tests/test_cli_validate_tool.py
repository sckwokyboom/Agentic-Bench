from abench.cli import main


def test_validate_tool_cli_reports_registered(tmp_path, monkeypatch, capsys):
    # Minimal experiment YAML (host sandbox, so no docker needed).
    fixture = tmp_path / "fix"; fixture.mkdir(); (fixture / "a.py").write_text("x=1\n")
    ref = tmp_path / "ref"; ref.mkdir()
    exp = tmp_path / "exp.yaml"
    exp.write_text(
        "name: t\n"
        f"fixture_path: {fixture}\n"
        f"reference_path: {ref}\n"
        "task_prompt: t\nsystem_prompt: s\nmodel: deepseek/deepseek-chat\n"
        f"output_dir: {tmp_path / 'runs'}\n"
        "conditions: [{name: baseline}]\n"
        "opencode: {agent: abench, sandbox: {mode: none}}\n")
    tool = tmp_path / "mytool.ts"
    tool.write_text("export default {}\n")

    # Stub validate_tool so the CLI test does not need a real opencode.
    import abench.tool_validation as tv
    from abench.tool_validation import ToolValidation
    monkeypatch.setattr(
        tv, "validate_tool",
        lambda *a, **k: ToolValidation("mytool", True, [], 0, "{}"))

    rc = main(["validate-tool", str(exp), str(tool)])
    assert rc == 0
    assert "mytool" in capsys.readouterr().out
