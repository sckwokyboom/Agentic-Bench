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


def test_condition_schema_exposes_new_fields():
    from abench_ui.schema import experiment_json_schema
    s = experiment_json_schema()
    cond = s["$defs"]["Condition"]["properties"]
    assert set(cond) >= {
        "name", "augmentation", "augmentation_kind", "overlay", "tools",
        "orchestration", "engine", "system_prompt",
    }
    # orchestration is now an enum (nullable), not a free string
    orch = cond["orchestration"]
    # pydantic v2 emits Literal|None as anyOf[{enum:[...]},{type:null}]
    # tolerate: top-level enum, anyOf-const, or anyOf-enum shapes
    flat = (
        orch.get("enum")
        or [b.get("const") for b in orch.get("anyOf", []) if "const" in b]
        or [v for b in orch.get("anyOf", []) for v in (b.get("enum") or [])]
    )
    assert "phased_runtime" in (flat or [])
    assert cond["engine"]["default"] == "python"
    assert cond["augmentation_kind"]["default"] == "text"
