"""Safe trace exporter (tools/export_safe_trace.py): keeps analysis-relevant
content, redacts everything sensitive (ids, URLs, secrets, usernames, raw outputs)."""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "export_safe_trace.py"


def _seed(tmp_path: Path) -> Path:
    rd = tmp_path / "augmented" / "rep_0"
    rd.mkdir(parents=True)
    (rd / "manifest.json").write_text(json.dumps({"condition": "augmented", "rep": 0}))
    (rd / "trace.json").write_text(json.dumps({
        "started_at": 1000.0, "ended_at": 1100.0, "finished": True,
        "interrupted_reason": None,
        "isolation_nonce": "NONCE9", "message_id": "msg_SECRET",
        "tokens_in": 1000, "tokens_out": 200,
        "n_service_errors": 1,
        "service_error_messages": ["error from https://internal.corp/v1 reqid deadbeefdeadbeefdeadbeef"],
        "verify_status": "failed", "verify_reason": "tests_failed",
        "verify_message": "1 of 2281 failed",
        "verify_command": "./gradlew test --continue",
        "verify_passed_count": 2280, "verify_failed_count": 1, "verify_expected_total": 2437,
        "verify_failed_names": ["picocli.HelpTest.testX"],
        "steps": [
            {"kind": "tool_call", "turn": 0, "ts": 1001.0, "tool_name": "bash",
             "tool_call_id": "call_SECRET123",
             "tool_args": {"command": "grep -rn putValue /Users/corpuser/proj/src"}},
            {"kind": "tool_call", "turn": 0, "ts": 1002.0, "tool_name": "grep",
             "tool_args": {"pattern": "TextTable", "path": "src"}},
            {"kind": "reasoning", "turn": 1, "ts": 1003.0,
             "text": "check https://internal.corp/api and email me@corp.com"},
            {"kind": "file_edit", "turn": 1, "ts": 1004.0,
             "path": "/tmp/abench-NONCE9/src/main/java/picocli/CommandLine.java",
             "patch": "--- a/src/X.java\n+++ b/tmp/abench-NONCE9/src/X.java\n"
                      "+  return new Cell(col,row); // token sk-ABCDEFGH12345\n"},
            {"kind": "tool_result", "turn": 0, "ts": 1005.0, "tool_call_id": "call_SECRET123",
             "output": "matches in /Users/corpuser/proj Authorization: Bearer abcd1234zzzz https://internal.corp"},
        ],
    }))
    return rd


def _run(path: Path, *extra):
    r = subprocess.run([sys.executable, str(SCRIPT), str(path), *extra],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r


def test_safe_export_keeps_analysis_fields(tmp_path):
    rd = _seed(tmp_path)
    _run(rd)
    bundle = json.loads((rd / "safe-traces.json").read_text())
    assert bundle["schema"] == "abench-safe-trace/v1"
    assert bundle["n_traces"] == 1
    tr = bundle["traces"][0]
    assert tr["condition"] == "augmented" and tr["rep"] == 0
    # tool calls + args preserved (the core of navigation analysis)
    assert tr["tool_calls_by_name"] == {"bash": 1, "grep": 1}
    assert tr["steps"][0]["args"]["command"].startswith("grep -rn putValue")
    assert tr["steps"][1]["args"]["pattern"] == "TextTable"
    # diff + repo-relative path tail preserved
    assert "return new Cell(col,row)" in tr["steps"][3]["patch"]
    assert "picocli/CommandLine.java" in tr["steps"][3]["path"]
    # relative timing, not wall-clock
    assert tr["steps"][0]["t"] == 1.0 and tr["duration_s"] == 100.0
    # safe numeric verify facts preserved
    assert tr["verify"]["expected_total"] == 2437 and tr["verify"]["passed_count"] == 2280


def test_safe_export_redacts_everything_sensitive(tmp_path):
    rd = _seed(tmp_path)
    _run(rd)
    blob = (rd / "safe-traces.json").read_text()
    for leak in [
        "corpuser",                  # username
        "internal.corp",             # internal URL host
        "me@corp.com",               # email
        "sk-ABCDEFGH12345",          # secret token
        "abcd1234zzzz",              # bearer token (lived only in the raw output)
        "NONCE9",                    # isolation nonce
        "msg_SECRET", "call_SECRET123",  # message / tool-call ids
        "deadbeefdeadbeefdeadbeef",  # request id from a service-error message
        "matches in",                # raw tool OUTPUT text (excluded by default)
    ]:
        assert leak not in blob, f"LEAKED: {leak!r}"
    # the redaction report is populated
    bundle = json.loads(blob)
    assert bundle["redaction"] and sum(bundle["redaction"].values()) > 0


def test_safe_export_outputs_opt_in_are_scrubbed_and_truncated(tmp_path):
    rd = _seed(tmp_path)
    _run(rd, "--include-outputs", "--max-output-chars", "30")
    bundle = json.loads((rd / "safe-traces.json").read_text())
    blob = json.dumps(bundle)
    # output now present but scrubbed (no host/user/secret) and truncated
    result_step = next(s for s in bundle["traces"][0]["steps"] if s["kind"] == "tool_result")
    assert "output" in result_step and "truncated" in result_step["output"]
    assert "internal.corp" not in blob and "corpuser" not in blob and "abcd1234zzzz" not in blob


def test_safe_export_bundles_a_runs_root(tmp_path):
    _seed(tmp_path)
    # add a second rep under a different condition
    rd2 = tmp_path / "baseline" / "rep_0"
    rd2.mkdir(parents=True)
    (rd2 / "trace.json").write_text(json.dumps({"started_at": 0.0, "ended_at": 1.0, "steps": []}))
    _run(tmp_path, "-o", str(tmp_path / "out.json"))
    bundle = json.loads((tmp_path / "out.json").read_text())
    assert bundle["n_traces"] == 2


def test_digest_mode_drops_bodies_and_keeps_skeleton():
    from abench.safe_trace import build_bundle
    trace = {
        "started_at": 0.0, "ended_at": 10.0,
        "steps": [
            {"kind": "tool_call", "ts": 1.0, "tool_name": "grep",
             "tool_args": {"pattern": "putValue", "command": "x" * 500}},
            {"kind": "reasoning", "ts": 2.0, "text": "y" * 400},
            {"kind": "file_edit", "ts": 3.0, "path": "src/X.java",
             "patch": "--- a/src/X.java\n+++ b/src/X.java\n+line1\n+line2\n-old\n"},
        ],
    }
    b = build_bundle([(trace, {"condition": "augmented", "rep": 0})], digest=True)
    assert "digest" in b["policy"]
    steps = b["traces"][0]["steps"]
    edit = next(s for s in steps if s["kind"] == "file_edit")
    assert "patch" not in edit and edit["edit"] == {"added": 2, "removed": 1}
    tc = next(s for s in steps if s["kind"] == "tool_call")
    assert tc["args"]["pattern"] == "putValue"
    assert tc["args"]["command"].endswith("…") and len(tc["args"]["command"]) <= 201
    txt = next(s for s in steps if s["kind"] == "reasoning")
    assert txt["text"].endswith("…") and len(txt["text"]) <= 161


def test_non_digest_keeps_patch_body():
    from abench.safe_trace import build_bundle
    trace = {"steps": [{"kind": "file_edit", "path": "x", "patch": "+code line\n"}]}
    s = build_bundle([(trace, {})])["traces"][0]["steps"][0]
    assert "patch" in s and "edit" not in s
