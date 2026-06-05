"""The standalone slide-render utility (tools/render_results.py)."""
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "render_results.py"


def test_render_results_produces_labelled_html(tmp_path):
    csv = tmp_path / "r.csv"
    csv.write_text(
        "condition,rep,verify,success,duration_s,steps,tool_calls,test_runs,cost,service_errors\n"
        "baseline,0,passed,pass,300,20,30,1,0.01,0\n"
        "baseline,1,passed,pass,200,40,40,1,0.02,0\n"
        "augmented,0,failed,fail,250,30,40,9,0.03,0\n"
        "augmented,1,passed,pass,250,30,40,3,0.03,0\n"
    )
    out = tmp_path / "slide.html"
    r = subprocess.run(
        [sys.executable, str(SCRIPT), str(csv), "--model", "DeepSeek v4 flash",
         "--agent", "opencode", "--title", "T", "-o", str(out)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    h = out.read_text()
    # header labels
    assert "DeepSeek v4 flash" in h and "agent: opencode" in h and "runs: 4" in h
    # per-condition columns with counts
    assert "(n=2)" in h
    # success rate 100% (baseline, 2/2) vs 50% (augmented, 1/2) → Δ -50pp
    assert ">100%<" in h and ">50%<" in h and "-50pp" in h
    # steps mean equal (30.0 vs 30.0) → neutral 0.0%
    assert ">30.0<" in h


def test_render_results_empty_csv_errors(tmp_path):
    csv = tmp_path / "empty.csv"
    csv.write_text("condition,rep,success\n")  # header only, no rows
    r = subprocess.run([sys.executable, str(SCRIPT), str(csv)],
                       capture_output=True, text=True)
    assert r.returncode != 0
