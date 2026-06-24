"""Graph-derived 'blast radius' for the phased+graph ablation.

Builds a predicate "does this failing test exercise the target method?" from the
precomputed graph coverage (`.impact/coverage.json` = {method_fqn: [test ids]}).
The phased+graph controller uses it to FOCUS the diagnose loop on failures inside
the change's blast radius (vs chasing unrelated/pre-existing ones). Injected into
the pure orchestrator as a callable so the orchestrator stays graph-agnostic.

Best-effort: returns None if the graph data is missing or matches nothing, so
phased+graph then degrades to plain phased (recorded as a controller event).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

from .failure_report import TestFailure


def _norm_key(name: str) -> "str | None":
    """Normalize a test identifier to ``simpleclass.method`` (lowercased) so a
    gradle line, an FQN ("pkg.Class.method") and a bare "Class.method" compare
    equal. Mirrors docker/impact_cli.py:_norm_key (keep in sync)."""
    s = (name or "").strip()
    if not s:
        return None
    if ">" in s:                                   # gradle: "[pkg.]Class > method[(...)]"
        cls, _, method = s.partition(">")
        cls = cls.strip().split(".")[-1]
        method = re.split(r"[(\s]", method.strip())[0]
    elif "." in s:                                 # FQN or Class.method
        cls_full, _, method = s.rpartition(".")
        cls = cls_full.split(".")[-1]
        method = re.split(r"[(\s]", method.strip())[0]
    else:
        return None
    if not cls or not method:
        return None
    return f"{cls}.{method}".lower()


def blast_radius_keys(coverage: dict, target_methods: "list[str]") -> "set[str]":
    """Normalized keys of every test that covers a target method, per the graph
    coverage map ({method_fqn: [test ids]}). A coverage key matches when its
    method-name part is in target_methods."""
    wanted = set(target_methods or [])
    keys: set[str] = set()
    for fqn, tests in (coverage or {}).items():
        if not isinstance(fqn, str):
            continue
        method = fqn.rsplit(".", 1)[-1].split("$")[-1]   # method name (strip pkg/class$nesting)
        if method in wanted:
            for t in tests or []:
                k = _norm_key(t)
                if k:
                    keys.add(k)
    return keys


def make_blast_radius_predicate(
    impact_dir: Path, target_methods: "list[str]"
) -> "Callable[[TestFailure], bool] | None":
    """Predicate: does a failing test exercise a target method (per the graph)?
    None when the coverage data is absent or no covering tests are found."""
    cov_path = Path(impact_dir) / "coverage.json"
    try:
        coverage = json.loads(cov_path.read_text())
    except (OSError, ValueError):
        return None
    keys = blast_radius_keys(coverage, target_methods)
    if not keys:
        return None

    def covers(f: TestFailure) -> bool:
        k = _norm_key(f"{f.classname}.{f.name}")
        return k is not None and k in keys

    return covers
