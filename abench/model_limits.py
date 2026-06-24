"""Best-effort lookup of a model's context window (max input+output tokens for
one request) from an OpenAI-compatible ``/v1/models`` endpoint — so the UI can
show "% of context used" without the operator typing the number.

For a self-hosted vLLM endpoint the window is set at launch (``--max-model-len``)
and no public catalog knows it, but vLLM reports it as ``max_model_len`` in
``/v1/models``. Everything here is best-effort: any failure returns None and the
UI simply falls back to absolute token counts.
"""
from __future__ import annotations

import json
import os
import urllib.request

# Field names different servers use for the context window, in priority order.
_FIELDS = ("max_model_len", "context_length", "context_window",
           "max_context_length", "max_seq_len")


def context_from_models(data: dict, model: str) -> "int | None":
    """Pure: pull the model's context window out of a parsed ``/v1/models``
    payload (vLLM ``max_model_len``, or OpenAI / models.dev-style fields). Prefers
    the entry whose id matches ``model`` (or its post-``/`` tail), else the first."""
    entries = data.get("data") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        return None
    tail = model.split("/", 1)[-1] if "/" in model else model
    chosen = next(
        (e for e in entries if isinstance(e, dict) and e.get("id") in (model, tail)),
        None,
    ) or entries[0]
    if not isinstance(chosen, dict):
        return None
    for k in _FIELDS:
        v = chosen.get(k)
        if isinstance(v, int) and v > 0:
            return v
    # models.dev / opencode style: nested limit.context
    lim = chosen.get("limit")
    if isinstance(lim, dict) and isinstance(lim.get("context"), int) and lim["context"] > 0:
        return lim["context"]
    return None


def fetch_context_window(base_url: str, api_key: "str | None", model: str,
                         timeout: float = 5.0) -> "int | None":
    """Best-effort GET ``{base_url}/models`` → the model's context window. None on
    any error (network, auth, parse, field absent)."""
    if not base_url:
        return None
    url = base_url.rstrip("/") + "/models"
    req = urllib.request.Request(url)
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8", "replace"))
        return context_from_models(data, model)
    except Exception:
        return None


def resolve_context_window(exp) -> "int | None":
    """The model's context window for an Experiment: the explicit override if set,
    otherwise a best-effort fetch from the first provider's endpoint. None when
    unknown. Duck-typed on ``exp`` (model_context_window, model, opencode.providers)."""
    override = getattr(exp, "model_context_window", None)
    if override:
        return override
    providers = getattr(getattr(exp, "opencode", None), "providers", None) or []
    if not providers:
        return None
    prov = providers[0]
    key = os.environ.get(prov.api_key_env) if getattr(prov, "api_key_env", None) else None
    return fetch_context_window(prov.base_url, key, exp.model)
