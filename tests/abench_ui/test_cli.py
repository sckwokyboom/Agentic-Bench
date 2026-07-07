from unittest.mock import patch

from abench_ui.cli import main


def test_cli_parses_and_calls_uvicorn(tmp_path):
    calls = {}

    def fake_run(app, **kwargs):
        calls["app"] = app
        calls.update(kwargs)

    # Pretend the SPA bundle is present so the bundle check passes without
    # depending on the gitignored build artefact on disk.
    index = tmp_path / "index.html"
    index.write_text("<html></html>")

    with patch("abench_ui.cli._static_index_path", return_value=index), patch(
        "abench_ui.cli.uvicorn.run", side_effect=fake_run
    ):
        rc = main([
            "--port", "9999",
            "--host", "127.0.0.1",
            "--experiments-dir", str(tmp_path),
        ])

    assert rc == 0
    assert calls["port"] == 9999
    assert calls["host"] == "127.0.0.1"


def test_expose_binds_all_interfaces(tmp_path):
    """--expose serves on 0.0.0.0 (LAN) regardless of --host, so teammates can open it."""
    calls = {}
    index = tmp_path / "index.html"
    index.write_text("<html></html>")

    with patch("abench_ui.cli._static_index_path", return_value=index), patch(
        "abench_ui.cli.uvicorn.run", side_effect=lambda app, **k: calls.update(k)
    ):
        rc = main(["--expose", "--experiments-dir", str(tmp_path)])

    assert rc == 0
    assert calls["host"] == "0.0.0.0"


def test_default_host_is_localhost_only(tmp_path):
    """Without --expose the default stays localhost — no accidental LAN exposure."""
    calls = {}
    index = tmp_path / "index.html"
    index.write_text("<html></html>")

    with patch("abench_ui.cli._static_index_path", return_value=index), patch(
        "abench_ui.cli.uvicorn.run", side_effect=lambda app, **k: calls.update(k)
    ):
        rc = main(["--experiments-dir", str(tmp_path)])

    assert rc == 0
    assert calls["host"] == "127.0.0.1"


def test_main_returns_2_when_bundle_missing(monkeypatch, capsys, tmp_path):
    """If abench_ui/static/index.html is absent, abench-ui refuses to start
    and never reaches uvicorn.run."""
    from abench_ui import cli

    monkeypatch.setattr(cli, "_static_index_path", lambda: tmp_path / "missing.html")

    rc = cli.main([])
    assert rc == 2
    assert "SPA bundle not found" in capsys.readouterr().err


def test_main_skips_bundle_check_when_flag_set(monkeypatch, tmp_path):
    """--skip-bundle-check lets main proceed without a built bundle.
    Swap uvicorn.run for a no-op so the function returns 0 without binding."""
    from abench_ui import cli

    monkeypatch.setattr(cli, "_static_index_path", lambda: tmp_path / "missing.html")
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **k: None)

    rc = cli.main(["--skip-bundle-check", "--experiments-dir", str(tmp_path)])
    assert rc == 0
