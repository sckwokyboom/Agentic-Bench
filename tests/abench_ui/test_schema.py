from abench_ui.schema import experiment_json_schema


def test_schema_has_required_fields():
    schema = experiment_json_schema()
    assert schema["type"] == "object"
    props = schema["properties"]
    for required_field in (
        "name", "fixture_path", "reference_path",
        "task_prompt", "system_prompt", "model",
        "conditions", "repetitions", "output_dir",
        "verify", "isolation",
    ):
        assert required_field in props, f"missing {required_field}"


def test_schema_includes_nested_verify_isolation():
    schema = experiment_json_schema()
    defs = schema.get("$defs", {}) or schema.get("definitions", {})
    # pydantic v2 puts nested models in $defs
    assert any("VerifyCfg" in k or "Verify" in k for k in defs)
    assert any("IsolationCfg" in k or "Isolation" in k for k in defs)


def test_schema_is_json_serialisable():
    import json
    json.dumps(experiment_json_schema())  # raises if not serialisable
