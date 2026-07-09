from abench.config import Condition, OrchestrationCfg


def test_condition_accepts_rcc():
    c = Condition(name="rcc", orchestration="rcc")
    assert c.orchestration == "rcc"


def test_orchestration_cfg_rcc_knobs_default():
    o = OrchestrationCfg()
    assert o.rcc_max_attempts == 2
    assert o.rcc_subset_class_cap == 15
