# tests/test_metrics.py
from abench.metrics import MetricsConfig, extract
from abench.trace_model import Step, StepKind, Trace


def _cfg():
    return MetricsConfig(
        test_command_patterns=["pytest", r"(npm|pnpm|yarn)( run)? test"],
        shell_tool_names=["bash"],
        read_tool_names=["read"],
        search_tool_names=["grep", "glob", "list"],
        command_arg_keys=["command", "cmd"],
    )


def _trace():
    return Trace(
        started_at=0.0,
        ended_at=12.0,
        tokens_in=100,
        tokens_out=200,
        finished=True,
        steps=[
            Step(kind=StepKind.ASSISTANT_TEXT, ts=0.0, turn=0, text="plan"),
            Step(kind=StepKind.TOOL_CALL, ts=1.0, turn=0,
                 tool_name="read", tool_args={"path": "a.py"}),
            Step(kind=StepKind.TOOL_CALL, ts=2.0, turn=0,
                 tool_name="grep", tool_args={"pattern": "foo"}),
            Step(kind=StepKind.ASSISTANT_TEXT, ts=3.0, turn=1, text="editing"),
            Step(kind=StepKind.FILE_EDIT, ts=4.0, turn=1, path="a.py", patch="x"),
            Step(kind=StepKind.TOOL_CALL, ts=5.0, turn=2,
                 tool_name="bash", tool_args={"command": "pytest -q"}),
            Step(kind=StepKind.TOOL_CALL, ts=6.0, turn=2,
                 tool_name="bash", tool_args={"command": "ls -la"}),
        ],
    )


def test_extract_flags_stuck_only_on_looping():
    base = dict(started_at=0.0, ended_at=1.0, steps=[])
    assert extract(Trace(**base, interrupted_reason="looping"), "", _cfg())["stuck"] is True
    for reason in (None, "timeout", "stalled", "rate_limit", "cancelled"):
        m = extract(Trace(**base, interrupted_reason=reason), "", _cfg())
        assert m["stuck"] is False, reason


def test_extract_counts_metrics():
    patch = (
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
        "@@ -0,0 +1,1 @@\n+added line\n"
    )
    m = extract(_trace(), patch, _cfg())
    assert m["n_steps"] == 3          # turns 0,1,2
    assert m["n_tool_calls"] == 4
    assert m["tool_calls_by_name"] == {"read": 1, "grep": 1, "bash": 2}
    assert m["n_test_runs"] == 1      # only "pytest -q" matches
    assert m["n_reads"] == 1
    assert m["n_searches"] == 1
    assert m["n_files_edited"] == 1
    assert m["diff_lines_added"] == 1
    assert m["duration_s"] == 12.0
    assert m["time_to_first_edit_s"] == 4.0
    assert m["finished"] is True
    assert m["success"] is None


def test_time_to_first_edit_from_edit_tool_call_when_no_patch_parts():
    # Regression: opencode 1.15.x emits no part.type=="patch" events, so the
    # normalized trace carries the edit only as a TOOL_CALL named "edit" —
    # there are no FILE_EDIT steps to time against.
    trace = Trace(
        started_at=100.0,
        ended_at=700.0,
        finished=False,
        interrupted_reason="timeout",
        steps=[
            Step(kind=StepKind.TOOL_CALL, ts=110.0, turn=0,
                 tool_name="read", tool_args={"path": "a.py"}),
            Step(kind=StepKind.TOOL_CALL, ts=510.0, turn=1,
                 tool_name="edit", tool_args={"filePath": "a.py"},
                 tool_call_id="c1"),
            Step(kind=StepKind.TOOL_RESULT, ts=511.0, turn=1, tool_call_id="c1"),
        ],
    )
    m = extract(trace, "", _cfg())
    assert m["time_to_first_edit_s"] == 410.0


def test_time_to_first_edit_ignores_zero_ts_edit_calls():
    # normalize() maps a missing state.time.start to ts=0.0 (epoch zero);
    # that must not yield a bogus negative time_to_first_edit_s.
    trace = Trace(
        started_at=100.0,
        steps=[
            Step(kind=StepKind.TOOL_CALL, ts=0.0, turn=0,
                 tool_name="edit", tool_args={}),
        ],
    )
    m = extract(trace, "", _cfg())
    assert m["time_to_first_edit_s"] is None


def test_time_to_first_edit_takes_earliest_of_file_edit_and_edit_call():
    trace = Trace(
        started_at=0.0,
        steps=[
            Step(kind=StepKind.TOOL_CALL, ts=3.0, turn=0,
                 tool_name="write", tool_args={}),
            Step(kind=StepKind.FILE_EDIT, ts=5.0, turn=1, path="a.py", patch="x"),
        ],
    )
    m = extract(trace, "", _cfg())
    assert m["time_to_first_edit_s"] == 3.0


def test_extract_copies_verify_fields_and_auto_success_passed():
    cfg = _cfg()
    trace = Trace(
        started_at=0.0, ended_at=10.0,
        finished=True,
        verify_status="passed",
        verify_command="./gradlew test",
        verify_duration_s=12.0,
        verify_passed_count=142,
        verify_failed_count=0,
        steps=[],
    )
    m = extract(trace, "", cfg)
    assert m["verify_status"] == "passed"
    assert m["verify_passed_count"] == 142
    assert m["success"] is True


def test_extract_auto_success_failed():
    cfg = _cfg()
    trace = Trace(
        started_at=0.0, ended_at=10.0,
        finished=True,
        verify_status="failed",
        verify_failed_count=3,
        steps=[],
    )
    m = extract(trace, "", cfg)
    assert m["success"] is False


def test_extract_auto_success_none_when_skipped():
    cfg = _cfg()
    trace = Trace(
        started_at=0.0, ended_at=10.0,
        finished=True,
        verify_status="skipped",
        steps=[],
    )
    m = extract(trace, "", cfg)
    assert m["success"] is None


def test_metrics_include_verify_reason_and_message():
    tr = Trace()
    tr.verify_status = "error"
    tr.verify_reason = "build_failed"
    tr.verify_message = "build failed — COMPILATION ERROR"
    m = extract(tr, "", _cfg())
    assert m["verify_reason"] == "build_failed"
    assert m["verify_message"] == "build failed — COMPILATION ERROR"
    assert m["success"] is None


def test_metrics_include_service_error_counters_and_source_changes():
    cfg = _cfg()
    tr = Trace(
        finished=False,
        interrupted_reason="rate_limit",
        n_service_errors=3,
        n_rate_limits=1,
        verify_insensitive=True,
    )
    # Non-empty patch → made_source_changes True
    m = extract(tr, "diff --git a/a.py b/a.py\n+x\n", cfg)
    assert m["n_service_errors"] == 3
    assert m["n_rate_limits"] == 1
    assert m["made_source_changes"] is True
    assert m["verify_insensitive"] is True


def test_metrics_made_source_changes_false_on_empty_patch():
    cfg = _cfg()
    m = extract(Trace(), "   \n", cfg)
    assert m["made_source_changes"] is False
    assert m["n_service_errors"] == 0
    assert m["n_rate_limits"] == 0
    assert m["verify_insensitive"] is False


from abench.metrics import _success_from_status


def test_success_from_status_rule():
    assert _success_from_status("passed") is True
    assert _success_from_status("failed") is False
    assert _success_from_status("error") is None
    assert _success_from_status("skipped") is None
    assert _success_from_status(None) is None


def test_n_tests_executed_parses_test_command_output():
    from abench.metrics import extract, MetricsConfig
    from abench.trace_model import Step, StepKind, Trace
    cfg = MetricsConfig(test_command_patterns=["pytest"], shell_tool_names=["bash"],
                        read_tool_names=["read"], search_tool_names=["grep"],
                        command_arg_keys=["command"])
    tr = Trace(steps=[
        Step(kind=StepKind.TOOL_CALL, tool_name="bash", tool_call_id="c1",
             tool_args={"command": "pytest -q"}),
        Step(kind=StepKind.TOOL_RESULT, tool_call_id="c1", output="5 passed, 1 failed in 0.3s"),
    ])
    m = extract(tr, "", cfg)
    assert m["n_test_runs"] == 1
    assert m["n_tests_executed"] == 6
    assert m["tokens_reasoning"] is None
    assert "cache_read" in m and "cache_write" in m


def test_n_tests_executed_zero_when_unparseable():
    from abench.metrics import extract, MetricsConfig
    from abench.trace_model import Step, StepKind, Trace
    cfg = MetricsConfig(test_command_patterns=["pytest"], shell_tool_names=["bash"],
                        read_tool_names=["read"], search_tool_names=["grep"],
                        command_arg_keys=["command"])
    tr = Trace(steps=[
        Step(kind=StepKind.TOOL_CALL, tool_name="bash", tool_call_id="c1",
             tool_args={"command": "pytest"}),
        Step(kind=StepKind.TOOL_RESULT, tool_call_id="c1", output="weird output"),
    ])
    m = extract(tr, "", cfg)
    assert m["n_test_runs"] == 1 and m["n_tests_executed"] == 0


def test_n_tests_executed_robust_to_command_prefix():
    """A gradle test run wrapped in `cd ... &&` still parses. The old first-token
    parser returned 0 here — which is why baseline runs showed 0 tests executed
    while augmented (bare `./gradlew test`) showed thousands."""
    from abench.metrics import extract, MetricsConfig
    from abench.trace_model import Step, StepKind, Trace
    cfg = MetricsConfig(test_command_patterns=[r"gradlew?\b.*test"],
                        shell_tool_names=["bash"], read_tool_names=["read"],
                        search_tool_names=["grep"], command_arg_keys=["command"])
    tr = Trace(steps=[
        Step(kind=StepKind.TOOL_CALL, tool_name="bash", tool_call_id="c1",
             tool_args={"command": "cd /tmp/picocli && ./gradlew test"}),
        Step(kind=StepKind.TOOL_RESULT, tool_call_id="c1",
             output="BUILD SUCCESSFUL\n263 tests completed, 0 failed"),
    ])
    m = extract(tr, "", cfg)
    assert m["n_test_runs"] == 1
    assert m["n_tests_executed"] == 263


def test_n_tests_executed_sums_across_runs():
    """tests_executed is the TOTAL test-case executions across all the agent's
    test runs (an effort/flailing proxy under the 'run all tests' instruction)."""
    from abench.metrics import extract, MetricsConfig
    from abench.trace_model import Step, StepKind, Trace
    cfg = MetricsConfig(test_command_patterns=["pytest"], shell_tool_names=["bash"],
                        read_tool_names=["read"], search_tool_names=["grep"],
                        command_arg_keys=["command"])
    tr = Trace(steps=[
        Step(kind=StepKind.TOOL_CALL, tool_name="bash", tool_call_id="c1",
             tool_args={"command": "pytest"}),
        Step(kind=StepKind.TOOL_RESULT, tool_call_id="c1", output="10 passed in 1s"),
        Step(kind=StepKind.TOOL_CALL, tool_name="bash", tool_call_id="c2",
             tool_args={"command": "pytest"}),
        Step(kind=StepKind.TOOL_RESULT, tool_call_id="c2", output="4 passed in 1s"),
    ])
    m = extract(tr, "", cfg)
    assert m["n_test_runs"] == 2
    assert m["n_tests_executed"] == 14  # 10 + 4, summed across the two runs


def test_tests_pass_rate_is_passed_over_total():
    from abench.metrics import extract, MetricsConfig
    from abench.trace_model import Trace
    cfg = MetricsConfig(test_command_patterns=["pytest"], shell_tool_names=["bash"],
                        read_tool_names=["read"], search_tool_names=["grep"],
                        command_arg_keys=["command"])
    # 2198/2200 passed → ~0.999 (captures a "nearly all passed" run that
    # success=False would hide).
    m = extract(Trace(verify_passed_count=2198, verify_failed_count=2), "", cfg)
    assert round(m["tests_pass_rate"], 4) == round(2198 / 2200, 4)
    # no verify counts → None
    assert extract(Trace(), "", cfg)["tests_pass_rate"] is None


def test_tests_pass_rate_uses_expected_total_denominator():
    """When the full expected suite size is known, tests that never ran in a
    failing run (early abort / non-compiling module) count as not-passed."""
    from abench.metrics import extract, MetricsConfig
    from abench.trace_model import Trace
    cfg = MetricsConfig(test_command_patterns=["pytest"], shell_tool_names=["bash"],
                        read_tool_names=["read"], search_tool_names=["grep"],
                        command_arg_keys=["command"])
    # 2280 passed, 1 failed, but the full suite is 2437 → 156 never ran.
    tr = Trace(verify_passed_count=2280, verify_failed_count=1, verify_expected_total=2437)
    assert round(extract(tr, "", cfg)["tests_pass_rate"], 6) == round(2280 / 2437, 6)
    # expected <= passed+failed (or absent) → denominator stays passed+failed.
    tr2 = Trace(verify_passed_count=2280, verify_failed_count=1, verify_expected_total=2281)
    assert round(extract(tr2, "", cfg)["tests_pass_rate"], 6) == round(2280 / 2281, 6)
    tr3 = Trace(verify_passed_count=2280, verify_failed_count=1)  # no expected → fallback
    assert round(extract(tr3, "", cfg)["tests_pass_rate"], 6) == round(2280 / 2281, 6)
    tr4 = Trace(verify_passed_count=2437, verify_failed_count=0, verify_expected_total=2437)
    assert extract(tr4, "", cfg)["tests_pass_rate"] == 1.0


def test_default_test_patterns_cover_gradle_and_maven():
    import re
    from abench.config import DEFAULT_TEST_PATTERNS

    def matches(cmd: str) -> bool:
        return any(re.search(p, cmd) for p in DEFAULT_TEST_PATTERNS)

    assert matches("./gradlew test")
    assert matches("gradle :picocli-core:test")
    assert matches("mvn test")
    assert matches("./mvnw verify")
    assert not matches("./gradlew build")  # not a test task
    assert not matches("git status")


def test_obs_tokens_attributed_by_tool():
    """Observation (tool-result) token cost is estimated (≈chars/4) and attributed
    to the calling tool by tool_call_id."""
    from abench.metrics import extract, MetricsConfig
    from abench.trace_model import Step, StepKind, Trace
    cfg = MetricsConfig(test_command_patterns=["pytest"], shell_tool_names=["bash"],
                        read_tool_names=["read"], search_tool_names=["grep"],
                        command_arg_keys=["command"])
    tr = Trace(steps=[
        Step(kind=StepKind.TOOL_CALL, tool_name="grep", tool_call_id="c1", tool_args={"pattern": "x"}),
        Step(kind=StepKind.TOOL_RESULT, tool_call_id="c1", output="a" * 400),  # ≈100 tok
        Step(kind=StepKind.TOOL_CALL, tool_name="read", tool_call_id="c2", tool_args={"path": "f"}),
        Step(kind=StepKind.TOOL_RESULT, tool_call_id="c2", output="b" * 40),   # ≈10 tok
    ])
    m = extract(tr, "", cfg)
    assert m["obs_tokens_by_tool"] == {"grep": 100, "read": 10}
    assert m["obs_tokens_total"] == 110
