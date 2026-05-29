from unittest.mock import patch

from abench_ui.cli import main


def test_cli_parses_and_calls_uvicorn(tmp_path):
    calls = {}

    def fake_run(app, **kwargs):
        calls["app"] = app
        calls.update(kwargs)

    with patch("abench_ui.cli.uvicorn.run", side_effect=fake_run):
        rc = main([
            "--port", "9999",
            "--host", "127.0.0.1",
            "--experiments-dir", str(tmp_path),
        ])

    assert rc == 0
    assert calls["port"] == 9999
    assert calls["host"] == "127.0.0.1"
