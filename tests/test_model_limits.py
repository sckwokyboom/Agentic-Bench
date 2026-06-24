from abench.model_limits import context_from_models


def test_context_from_models_vllm_max_model_len():
    data = {"object": "list", "data": [
        {"id": "IDE-GPU-3/devstral2-24B", "object": "model", "max_model_len": 131072},
    ]}
    assert context_from_models(data, "IDE-GPU-3/devstral2-24B") == 131072


def test_context_from_models_matches_by_tail_else_first():
    data = {"data": [{"id": "other", "max_model_len": 4096},
                     {"id": "devstral2-24B", "context_length": 65536}]}
    # "prov/devstral2-24B" → tail "devstral2-24B" matches the second entry
    assert context_from_models(data, "prov/devstral2-24B") == 65536
    # no id match → first entry
    assert context_from_models(data, "unknown") == 4096


def test_context_from_models_nested_limit_context():
    data = {"data": [{"id": "m", "limit": {"context": 200000, "output": 8192}}]}
    assert context_from_models(data, "m") == 200000


def test_context_from_models_none_when_absent_or_malformed():
    assert context_from_models({"data": [{"id": "m"}]}, "m") is None
    assert context_from_models({}, "m") is None
    assert context_from_models({"data": []}, "m") is None
    assert context_from_models({"data": [{"id": "m", "max_model_len": "lots"}]}, "m") is None
