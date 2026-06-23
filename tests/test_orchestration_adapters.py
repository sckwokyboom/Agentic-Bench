from dataclasses import dataclass
from abench.trace_model import Step, StepKind, Trace
from abench.orchestration_adapters import (
    eval_from_junit, extract_phase_text, make_phase_runner, build_orchestrator_config,
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
                     timeout_s, agent_tools, on_event):
            calls.update(workdir=workdir, model=model, user_message=user_message,
                         agent_tools=agent_tools)
            return _Res(Trace(steps=[Step(kind=StepKind.ASSISTANT_TEXT, ts=1.0,
                                          text="CONTRACT: ...")]))

    runner = make_phase_runner(_FakeClient(), workdir="/wd", system_prompt="sys",
                               model="m", timeout_s=60, on_event=lambda e: None)
    out = runner("understand", "study the method", ["read", "grep"])
    assert out.text == "CONTRACT: ..."
    assert calls["agent_tools"] == {"read": True, "grep": True}
    assert calls["user_message"] == "study the method" and calls["workdir"] == "/wd"


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
