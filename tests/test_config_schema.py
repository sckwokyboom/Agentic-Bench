from abench.config import Experiment


def test_json_schema_carries_titles_and_descriptions():
    s = Experiment.model_json_schema()
    defs = s.get("$defs", {})
    props = s["properties"]
    assert props["repetitions"].get("description")
    assert props["target_file"].get("description")
    assert props["rate_limit_retries"].get("description")
    assert props["rate_limit_backoff_s"].get("description")
    metrics = defs["MetricsCfg"]["properties"]
    assert metrics["test_command_patterns"].get("description")
    assert metrics["command_arg_keys"].get("description")
    verify = defs["VerifyCfg"]["properties"]
    assert verify["command"].get("description")
    iso = defs["IsolationCfg"]["properties"]
    assert iso["nonce_prefix"].get("description")
    assert iso["shuffle_order"].get("description")


def test_json_schema_exposes_custom_providers_and_small_model():
    s = Experiment.model_json_schema()
    defs = s.get("$defs", {})
    assert "ProviderCfg" in defs
    prov = defs["ProviderCfg"]["properties"]
    assert prov["id"].get("description")
    assert prov["base_url"].get("description")
    assert prov["api_key_env"].get("description")
    oc = defs["OpenCodeCfg"]["properties"]
    assert oc["small_model"].get("description")
    assert oc["providers"].get("description")


def test_json_schema_guards_overlay_fields():
    s = Experiment.model_json_schema()
    defs = s.get("$defs", {})
    props = s["properties"]
    assert props["overlay_env"].get("description")
    cond = defs["Condition"]["properties"]
    assert cond["overlay"].get("description")
