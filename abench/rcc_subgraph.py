"""Deterministic mutational subgraph for RapidCausalCoder (rcc).

Built from the impact artifacts: ``.impact/coverage.json`` ({method_fqn: [test
fqns]} — the joern-precomputed neighborhood around the experiment targets) and
``.impact/methods.json`` ({method_fqn: {file,start,end}} spans anchored to the
seed). The subgraph = the changed method + neighbors ranked by covering-test
overlap with it (top-K). This ranking IS the MVP filter node — the seam where
k-medoid / explicit call-graph-distance filters slot in later. Pure; no LLM.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RccSubgraph:
    target_fqn: str
    methods: list[str]                      # target first, then ranked neighbors
    test_fqns: list[str]                    # union of covering tests (sorted)
    test_classes: list[str]                 # distinct test-class FQNs (sorted)
    sources: dict[str, str] = field(default_factory=dict)   # method_fqn -> snippet
    # Pairwise shared-test-coverage between subgraph methods: (a, b, shared_count),
    # sorted by count desc then (a, b). The ONLY structural relation this subgraph
    # carries (no call-graph edge artifact exists — see module docstring); fed into
    # Alpha/Gamma so they get SOME relational grounding instead of a bag of
    # unrelated method snippets. Zero-overlap pairs are omitted (not a real signal).
    shared_test_edges: list[tuple[str, str, int]] = field(default_factory=list)


def _load(path: Path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def find_target_fqn(coverage: dict, target_methods: "list[str]") -> "str | None":
    """First coverage key whose method-name part (sans package/class$nesting) is
    in target_methods — the same matching rule as graph_cover.blast_radius_keys."""
    wanted = set(target_methods or [])
    for fqn in coverage or {}:
        if isinstance(fqn, str) and fqn.rsplit(".", 1)[-1].split("$")[-1] in wanted:
            return fqn
    return None


def read_span(workdir: Path, meta: dict, margin: int = 15, cap: int = 1200) -> str:
    """The method's source lines (per the methods.json span) ± margin, capped.
    Spans are anchored to the seed; agent edits may shift lines — the margin
    absorbs small drift, and a missing/renamed file degrades to ''. """
    try:
        text = (Path(workdir) / meta["file"]).read_text(encoding="utf-8",
                                                        errors="replace")
    except (OSError, KeyError, TypeError):
        return ""
    lines = text.splitlines()
    start = max(0, int(meta.get("start", 1)) - 1 - margin)
    end = min(len(lines), int(meta.get("end", start + 1)) + margin)
    return "\n".join(lines[start:end])[:cap]


def _pairwise_shared_test_edges(methods: list[str],
                                coverage: dict) -> "list[tuple[str, str, int]]":
    """Shared-test count for every unordered pair in `methods` (small set —
    O(k^2), cheap). Sorted desc by count then (a, b) for determinism."""
    edges: list = []
    for i, a in enumerate(methods):
        a_tests = set(coverage.get(a) or [])
        for b in methods[i + 1:]:
            n = len(a_tests & set(coverage.get(b) or []))
            if n > 0:
                edges.append((a, b, n))
    edges.sort(key=lambda e: (-e[2], e[0], e[1]))
    return edges


def build_subgraph(impact_dir, workdir, target_methods, *, k: int = 5,
                   margin: int = 15, cap: int = 1200) -> "RccSubgraph | None":
    """None when coverage is absent/empty or no target matches — the caller
    (Phase 2 wiring) then degrades to plain phased, mirroring phased_graph."""
    impact_dir = Path(impact_dir)
    coverage = _load(impact_dir / "coverage.json")
    if not isinstance(coverage, dict) or not coverage:
        return None
    target = find_target_fqn(coverage, target_methods)
    if target is None:
        return None
    t_tests = set(coverage.get(target) or [])

    def overlap(fqn: str) -> int:
        return len(t_tests & set(coverage.get(fqn) or []))

    neighbors = sorted((f for f in coverage if f != target),
                       key=lambda f: (-overlap(f), f))
    methods = [target] + [f for f in neighbors if overlap(f) > 0][:k]
    tests = sorted({t for m in methods for t in (coverage.get(m) or [])})
    classes = sorted({t.rsplit(".", 1)[0] for t in tests})
    meta = _load(impact_dir / "methods.json") or {}
    sources = {m: read_span(workdir, meta[m], margin=margin, cap=cap)
               for m in methods if m in meta}
    edges = _pairwise_shared_test_edges(methods, coverage)
    return RccSubgraph(target_fqn=target, methods=methods, test_fqns=tests,
                       test_classes=classes, sources=sources,
                       shared_test_edges=edges)
