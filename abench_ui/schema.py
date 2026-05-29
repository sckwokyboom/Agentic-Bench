"""Export the Experiment pydantic schema as JSON Schema for the frontend."""
from __future__ import annotations

from abench.config import Experiment


def experiment_json_schema() -> dict:
    """Returns the JSON Schema (draft 2020-12 by default in pydantic v2) for Experiment."""
    return Experiment.model_json_schema()
