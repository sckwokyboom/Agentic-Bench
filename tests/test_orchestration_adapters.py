from dataclasses import dataclass
from abench.trace_model import Step, StepKind, Trace
from abench.orchestration_adapters import (
    eval_from_junit, extract_phase_text, make_phase_runner, build_orchestrator_config,
    build_status, build_evidence_reader, make_suite_runner,
)


def test_eval_from_junit_full_breakdown(tmp_path):
    (tmp_path / "TEST-picocli.HelpTest.xml").write_text("""<?xml version="1.0"?>
<testsuite name="picocli.HelpTest" tests="5" failures="1" errors="1" skipped="1">
  <testcase name="ok1" classname="picocli.HelpTest"/>
  <testcase name="ok2" classname="picocli.HelpTest"/>
  <testcase name="tt" classname="picocli.HelpTest">
    <failure type="org.junit.ComparisonFailure" message="expected:&lt;a&gt; but was:&lt;b&gt;"/>
  </testcase>
  <testcase name="boom" classname="picocli.HelpTest">
    <error type="java.lang.IndexOutOfBoundsException" message="idx 5"/>
  </testcase>
  <testcase name="sk" classname="picocli.HelpTest"><skipped/></testcase>
</testsuite>""")
    ev = eval_from_junit(tmp_path)
    r = ev.result
    assert r.compiled is True and r.ran is True
    assert r.executed == 5 and r.failed == 2 and r.errors == 1 and r.skipped == 1
    assert r.passed == 2                        # 5 - (1 failure + 1 error) - 1 skipped
    # failures parsed for clustering (the <failure> and <error> testcases)
    kinds = sorted(f.kind for f in ev.failures)
    assert kinds == ["error", "failure"]


def test_eval_from_junit_no_results_marks_not_ran(tmp_path):
    ev = eval_from_junit(tmp_path, compiled=False, ran=True)
    assert ev.result.ran is False and ev.result.executed == 0


# ── build_status: compiled/ran from output + #executed ─────────────────────
# The orchestrator's regression gate rejects a round when compiled is False.
# Gradle/Maven print "BUILD FAILED" (and "error:") whenever ANY *test* fails —
# not only on compile errors — so deriving compiled purely from string-matching
# the output marks a perfectly-compiling, test-running suite as "does not
# compile". For picocli (hundreds of pre-existing unrelated failures) that made
# compiled ALWAYS False → no round ever accepted → the agent's work reverted.

def test_build_status_tests_ran_means_compiled_even_with_build_failed():
    out = "> Task :test FAILED\nThere were failing tests.\n\nBUILD FAILED in 2m 24s\n"
    compiled, ran = build_status(out, executed=2474)
    assert compiled is True and ran is True


def test_build_status_compile_error_when_nothing_executed():
    out = ("src/main/java/picocli/CommandLine.java:120: error: cannot find symbol\n"
           "COMPILATION ERROR\nBUILD FAILED\n")
    compiled, ran = build_status(out, executed=0)
    assert compiled is False and ran is False


def test_build_status_no_tests_no_compile_error_is_infra_not_compile_fail():
    # executed==0 with no compile markers = infra/no-tests (timeout, wrong cmd) —
    # "did not run", NOT a compile failure, so the gate's reason stays honest.
    out = "Starting a Gradle Daemon\nNo tests found for given includes\n"
    compiled, ran = build_status(out, executed=0)
    assert compiled is True and ran is False


def test_extract_phase_text_returns_last_nonempty_assistant_text():
    tr = Trace(steps=[
        Step(kind=StepKind.ASSISTANT_TEXT, ts=1.0, text="first"),
        Step(kind=StepKind.TOOL_CALL, ts=2.0, tool_name="read"),
        Step(kind=StepKind.ASSISTANT_TEXT, ts=3.0, text="the contract"),
        Step(kind=StepKind.ASSISTANT_TEXT, ts=4.0, text="   "),   # blank, skipped
    ])
    assert extract_phase_text(tr) == "the contract"
    assert extract_phase_text(Trace()) == ""


def test_make_phase_runner_scopes_tools_and_extracts_text():
    calls = {}

    @dataclass
    class _Res:
        trace: Trace

    class _FakeClient:
        def run_task(self, *, workdir, system_prompt, model, user_message,
                     timeout_s, agent_tools, on_event, cancel_event=None):
            calls.update(workdir=workdir, model=model, user_message=user_message,
                         agent_tools=agent_tools, cancel_event=cancel_event)
            return _Res(Trace(steps=[Step(kind=StepKind.ASSISTANT_TEXT, ts=1.0,
                                          text="CONTRACT: ...")]))

    sentinel = object()
    runner = make_phase_runner(_FakeClient(), workdir="/wd", system_prompt="sys",
                               model="m", timeout_s=60, on_event=lambda e: None,
                               cancel_event=sentinel)
    out = runner("understand", "study the method", ["read", "grep"])
    assert out.text == "CONTRACT: ..."          # extract still finds the agent's text
    assert calls["agent_tools"] == {"read": True, "grep": True}
    assert calls["user_message"] == "study the method" and calls["workdir"] == "/wd"
    assert calls["cancel_event"] is sentinel    # forwarded so a cancel kills the phase subprocess
    # the exact prompt is captured as a leading PHASE_PROMPT step (the LLM input)
    assert out.trace.steps[0].kind == StepKind.PHASE_PROMPT
    assert out.trace.steps[0].text == "study the method"
    assert out.trace.steps[0].phase == "understand"
    assert out.trace.steps[1].kind == StepKind.ASSISTANT_TEXT   # agent's step follows


_CAP_LINE = (
    '{"method":"picocli.CommandLine$Help$TextTable.putValue","args":["0","0",""],'
    '"stack":["picocli.CommandLine$Help$TextTable.putValue:17415",'
    '"picocli.HelpTest.testCatUsageFormat:2331","org.junit.X.run:1"]}\n'
)


def test_build_evidence_reader_reads_card(tmp_path):
    cap = tmp_path / "runtime-capture.jsonl"
    cap.write_text(_CAP_LINE)
    read = build_evidence_reader(cap, "TextTable.putValue")
    card = read()
    assert card and "RUNTIME EVIDENCE for TextTable.putValue" in card
    assert "putValue:17415" in card and "org.junit" not in card
    # absent capture -> None (no card, degrade gracefully)
    assert build_evidence_reader(tmp_path / "missing.jsonl", "x")() is None


def test_make_suite_runner_probe_injects_env_and_clears_capture(tmp_path):
    workdir = tmp_path / "wd"
    workdir.mkdir()
    cap = tmp_path / "runtime-capture.jsonl"
    cap.write_text("STALE\n")                          # must be cleared before the run
    # shell command records the injected JAVA_TOOL_OPTIONS so we can assert on it
    cmd = 'printf "%s" "$JAVA_TOOL_OPTIONS" > seen-env.txt'
    runner = make_suite_runner(workdir, cmd, timeout_s=30,
                               probe={"jar": "/opt/agent.jar",
                                      "targets": "picocli.CommandLine$Help$TextTable.putValue",
                                      "out": str(cap)})
    runner()
    assert not cap.exists()                             # capture cleared before the run
    seen = (workdir / "seen-env.txt").read_text()
    assert "-javaagent:/opt/agent.jar=picocli.CommandLine$Help$TextTable.putValue" in seen
    assert f"-Druntime.probe.out={cap}" in seen


def test_build_orchestrator_config_maps_mode_to_plan():
    @dataclass
    class _OrchCfg:
        contract_fields: list
        target_label: str = "putValue"
        max_diagnose_iters: int = 8
        no_progress_limit: int = 2
        cluster_cap: int = 5

    cfg = _OrchCfg(contract_fields=["WRAP", "SPAN"])
    assert build_orchestrator_config(cfg, "phased").with_plan is False
    assert build_orchestrator_config(cfg, "phased_plan").with_plan is True
    assert build_orchestrator_config(cfg, "phased").contract_fields == ["WRAP", "SPAN"]
    assert build_orchestrator_config(cfg, "phased").target_label == "putValue"
