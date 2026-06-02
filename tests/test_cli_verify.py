from unittest import mock

from abench import cli


def test_verify_single_run_prints_line(capsys):
    from abench.verify import VerifyResult
    fake = VerifyResult(status="failed", reason="tests_failed",
                        message="2 of 7 failed", passed_count=5, failed_count=2)
    with mock.patch("abench.cli.load_experiment", return_value=mock.Mock()), \
         mock.patch("abench.reverify.reverify_run", return_value=fake):
        rc = cli.main(["verify", "exp.yaml", "--condition", "baseline", "--rep", "0"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "baseline/rep_0" in out
    assert "failed/tests_failed" in out


def test_verify_whole_experiment(capsys):
    from abench.verify import VerifyResult
    rows = [("baseline", 0, VerifyResult(status="passed", reason="passed", message="ok",
                                         passed_count=7, failed_count=0))]
    with mock.patch("abench.cli.load_experiment", return_value=mock.Mock()), \
         mock.patch("abench.reverify.reverify_experiment", return_value=iter(rows)):
        rc = cli.main(["verify", "exp.yaml"])
    assert rc == 0
    assert "baseline/rep_0 → passed/passed" in capsys.readouterr().out


def test_verify_batch_threaded_to_experiment(capsys):
    from abench.verify import VerifyResult
    rows = [("baseline", 0, VerifyResult(status="passed", reason="passed", message="ok"))]
    with mock.patch("abench.cli.load_experiment", return_value=mock.Mock()), \
         mock.patch("abench.reverify.reverify_experiment",
                    return_value=iter(rows)) as rv:
        rc = cli.main(["verify", "exp.yaml", "--batch", "20260101-000000"])
    assert rc == 0
    _args, kwargs = rv.call_args
    assert kwargs.get("batch") == "20260101-000000"


def test_verify_batch_threaded_to_single_run():
    from abench.verify import VerifyResult
    fake = VerifyResult(status="passed", reason="passed", message="ok")
    with mock.patch("abench.cli.load_experiment", return_value=mock.Mock()), \
         mock.patch("abench.reverify.reverify_run", return_value=fake) as rv:
        rc = cli.main(["verify", "exp.yaml", "--condition", "baseline", "--rep", "0",
                       "--batch", "20260101-000000"])
    assert rc == 0
    _args, kwargs = rv.call_args
    assert kwargs.get("batch") == "20260101-000000"
