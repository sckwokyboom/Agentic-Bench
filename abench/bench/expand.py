"""Expand a benchmark experiment into the flat run plan: instance × condition × rep.

Mirrors the fixture-mode (condition × rep) plan, with the instance dimension added.
Runner wiring that consumes this is a later plan."""
from __future__ import annotations

from dataclasses import dataclass

from ..config import Condition, Experiment
from .base import Instance


@dataclass(frozen=True)
class BenchRun:
    instance: Instance
    condition: Condition
    rep: int


def expand_plan(exp: Experiment, instances: list[Instance]) -> list[BenchRun]:
    runs: list[BenchRun] = []
    for inst in instances:
        for cond in exp.conditions:
            for rep in range(exp.repetitions):
                runs.append(BenchRun(instance=inst, condition=cond, rep=rep))
    return runs
