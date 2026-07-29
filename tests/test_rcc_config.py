from abench.config import Condition, OrchestrationCfg


def test_condition_accepts_rcc():
    c = Condition(name="rcc", orchestration="rcc")
    assert c.orchestration == "rcc"


def test_orchestration_cfg_rcc_knobs_default():
    o = OrchestrationCfg()
    assert o.rcc_max_attempts == 2
    assert o.rcc_subset_class_cap == 15


def test_rcc_strict_defaults_on():
    # A benchmark must not silently run the CONTROL under the treatment's label:
    # a graph-build failure fails the rep instead of degrading to plain phased.
    assert OrchestrationCfg().rcc_strict is True
    assert OrchestrationCfg(rcc_strict=False).rcc_strict is False


def test_trace_records_degradation_not_just_the_log():
    from abench.config import MetricsCfg
    from abench.metrics import MetricsConfig, extract
    from abench.trace_model import Trace
    t = Trace()
    assert t.rcc_degraded is False and t.rcc_degrade_reason is None
    t.rcc_degraded = True
    t.rcc_degrade_reason = "graph builder returned no usable graph"
    m = extract(t, "", MetricsConfig(**MetricsCfg().model_dump()))
    # Downstream (report/UI/A-B aggregate) must see it WITHOUT grepping run.log.
    assert m["rcc_degraded"] is True
    assert "no usable graph" in m["rcc_degrade_reason"]
