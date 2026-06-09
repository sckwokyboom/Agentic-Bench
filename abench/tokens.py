"""Rough, provider-agnostic token estimate.

Used to compare the *relative* context cost of tool observations (grep/read/bash
outputs) — NOT an exact provider tokenization. ~4 chars/token is a decent rule of
thumb for English+code; the same heuristic is mirrored in the Web UI
(traceModel.estimateTokens) so on-screen and computed numbers agree.
"""
from __future__ import annotations

import math


def estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    return math.ceil(len(text) / 4)
