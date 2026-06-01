from pathlib import Path

from abench import runner
from abench.verify import VerifyResult


def test_run_one_writes_verify_output_log(tmp_path: Path):
    rundir = tmp_path / "rundir"
    rundir.mkdir()
    vr = VerifyResult(
        status="error", reason="build_failed",
        message="build failed — COMPILATION ERROR",
        command="mvn test", duration_s=12.3,
        passed_count=0, failed_count=0, raw_output="LOTS OF OUTPUT\nBUILD FAILURE\n",
    )
    runner._write_verify_log(rundir, vr)
    log = (rundir / "verify_output.log").read_text()
    assert "# command: mvn test" in log
    assert "build_failed" in log
    assert "BUILD FAILURE" in log
