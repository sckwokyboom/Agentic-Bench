from abench.config import Condition, OrchestrationCfg


def test_condition_orchestration_defaults_none():
    assert Condition(name="baseline").orchestration is None


def test_condition_orchestration_mode_parses():
    assert Condition(name="phased", orchestration="phased_plan").orchestration == "phased_plan"
    assert Condition(name="ph", orchestration="phased").orchestration == "phased"


def test_orchestration_cfg_defaults_and_fields():
    c = OrchestrationCfg(target_label="putValue")
    assert c.target_label == "putValue"
    assert c.max_diagnose_iters == 8 and c.no_progress_limit == 2 and c.cluster_cap == 5
