from abench.config import Experiment


def test_json_schema_carries_titles_and_descriptions():
    s = Experiment.model_json_schema()
    defs = s.get("$defs", {})
    props = s["properties"]
    assert props["repetitions"].get("description")
    assert props["target_file"].get("description")
    metrics = defs["MetricsCfg"]["properties"]
    assert metrics["test_command_patterns"].get("description")
    assert metrics["command_arg_keys"].get("description")
    verify = defs["VerifyCfg"]["properties"]
    assert verify["command"].get("description")
    iso = defs["IsolationCfg"]["properties"]
    assert iso["nonce_prefix"].get("description")
    assert iso["shuffle_order"].get("description")
