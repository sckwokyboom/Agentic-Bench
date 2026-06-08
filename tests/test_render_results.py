"""The standalone slide-render utility (tools/render_results.py)."""
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "render_results.py"


def test_render_results_produces_labelled_html(tmp_path):
    csv = tmp_path / "r.csv"
    csv.write_text(
        "condition,rep,verify,success,tests_pass_rate,duration_s,steps,tool_calls,"
        "test_runs,tests_executed,tokens_in,tokens_out,cost,service_errors\n"
        "baseline,0,passed,pass,1.0,300,20,30,1,2200,10000,2000,0.01,0\n"
        "baseline,1,passed,pass,1.0,200,40,40,1,2200,12000,2200,0.02,0\n"
        "augmented,0,failed,fail,0.99,250,30,40,9,2200,15000,3000,0.03,0\n"
        "augmented,1,passed,pass,0.99,250,30,40,3,2200,14000,2800,0.03,0\n"
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
    # duration shown in MINUTES (250s mean → 4.2 min); no cost row
    assert "duration (min)" in h and ">4.2<" in h
    assert "cost (" not in h
    # tests passed % with one decimal (baseline 100.0% vs augmented 99.0%)
    assert "tests passed %" in h and ">100.0%<" in h and ">99.0%<" in h
    # tests executed + token rows surface (means)
    assert "tests executed" in h and ">2200.0<" in h
    assert "tokens in" in h and "tokens out" in h and ">11000.0<" in h


def test_render_results_tests_passed_from_verify_counts_floored(tmp_path):
    """tests passed % is summed Σpassed/Σtotal and FLOORED: a 2198/2200 run makes
    augmented 99.95%, which must render 99.9% (not round up to 100.0%)."""
    csv = tmp_path / "r.csv"
    csv.write_text(
        "condition,rep,success,verify_passed,verify_failed\n"
        "baseline,0,pass,2200,0\n"
        "augmented,0,pass,2200,0\n"
        "augmented,1,fail,2198,2\n"
    )
    out = tmp_path / "slide.html"
    r = subprocess.run([sys.executable, str(SCRIPT), str(csv), "-o", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    h = out.read_text()
    assert "tests passed %" in h
    assert ">100.0%<" in h   # baseline: all pass
    assert ">99.9%<" in h    # augmented: (2200+2198)/4400 = 99.95% → floored, not 100.0%


def test_render_results_includes_tool_distribution(tmp_path):
    csv = tmp_path / "r.csv"
    csv.write_text(
        'condition,rep,success,tool_calls_by_name\n'
        'baseline,0,pass,"{""bash"": 4, ""read"": 6}"\n'
        'baseline,1,pass,"{""bash"": 2, ""read"": 4}"\n'
        'augmented,0,pass,"{""bash"": 10, ""grep"": 3}"\n'
    )
    out = tmp_path / "slide.html"
    r = subprocess.run([sys.executable, str(SCRIPT), str(csv), "-o", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    h = out.read_text()
    assert "Tool calls (mean per run)" in h
    assert ">bash<" in h and ">read<" in h and ">grep<" in h
    # baseline bash mean = (4+2)/2 = 3.0 ; augmented bash = 10/1 = 10.0
    assert ">3.0<" in h and ">10.0<" in h


def test_render_results_no_tool_section_without_column(tmp_path):
    csv = tmp_path / "r.csv"
    csv.write_text("condition,rep,success,steps\nbaseline,0,pass,10\n")
    out = tmp_path / "slide.html"
    subprocess.run([sys.executable, str(SCRIPT), str(csv), "-o", str(out)], check=True)
    assert "Tool calls (mean per run)" not in out.read_text()


def test_render_results_empty_csv_errors(tmp_path):
    csv = tmp_path / "empty.csv"
    csv.write_text("condition,rep,success\n")  # header only, no rows
    r = subprocess.run([sys.executable, str(SCRIPT), str(csv)],
                       capture_output=True, text=True)
    assert r.returncode != 0
