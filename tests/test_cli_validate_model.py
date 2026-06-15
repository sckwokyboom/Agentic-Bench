from abench.cli import main


def _exp_yaml(tmp_path):
    fixture = tmp_path / "fix"; fixture.mkdir(); (fixture / "a.py").write_text("x=1\n")
    ref = tmp_path / "ref"; ref.mkdir()
    exp = tmp_path / "exp.yaml"
    exp.write_text(
        "name: t\n"
        f"fixture_path: {fixture}\nreference_path: {ref}\n"
        "task_prompt: t\nsystem_prompt: s\nmodel: deepseek/deepseek-chat\n"
        f"output_dir: {tmp_path / 'runs'}\n"
        "conditions: [{name: baseline}]\n"
        "opencode:\n  agent: abench\n  sandbox: {mode: none}\n"
        "  providers:\n    - id: deepseek\n      base_url: https://api.deepseek.com/v1\n"
        "      models: [deepseek-chat]\n      api_key_env: DEEPSEEK_API_KEY\n")
    return exp


def test_validate_model_cli_reachable(tmp_path, monkeypatch, capsys):
    exp = _exp_yaml(tmp_path)
    import abench.reachability as r
    from abench.reachability import ReachabilityResult
    monkeypatch.setattr(r, "validate_reachability",
                        lambda *a, **k: ReachabilityResult(True, "ok", ""))
    assert main(["validate-model", str(exp)]) == 0
    assert "reachable" in capsys.readouterr().out.lower()


def test_validate_model_cli_unreachable_exit1(tmp_path, monkeypatch, capsys):
    exp = _exp_yaml(tmp_path)
    import abench.reachability as r
    from abench.reachability import ReachabilityResult
    monkeypatch.setattr(r, "validate_reachability",
                        lambda *a, **k: ReachabilityResult(False, "auth", "bad key"))
    assert main(["validate-model", str(exp)]) == 1
    assert "auth" in capsys.readouterr().out.lower()
