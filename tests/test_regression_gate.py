from abench.regression_gate import SuiteResult, decide


def _s(**kw):
    base = dict(compiled=True, ran=True, executed=100, passed=80, failed=20, errors=0, skipped=0)
    base.update(kw)
    return SuiteResult(**base)


def test_accept_when_more_pass():
    ok, _ = decide(_s(passed=80, failed=20), _s(passed=85, failed=15))
    assert ok


def test_reject_when_compile_broken():
    ok, why = decide(_s(), _s(compiled=False))
    assert not ok and "compile" in why.lower()


def test_reject_when_fewer_tests_executed_even_if_failed_drops():
    # failed dropped 20->5 only because 90 tests no longer ran
    ok, why = decide(_s(executed=100, passed=80, failed=20), _s(executed=10, passed=5, failed=5))
    assert not ok and "execut" in why.lower()


def test_reject_when_new_errors_despite_failed_drop():
    ok, _ = decide(_s(failed=20, errors=0), _s(failed=18, errors=3))
    assert not ok


def test_reject_when_no_improvement():
    ok, _ = decide(_s(passed=80, failed=20), _s(passed=80, failed=20))
    assert not ok
