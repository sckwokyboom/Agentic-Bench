"""RapidCausalCoder R2 — the graph layers (storage ≠ rendering).

GraphRaw (full MutationGraph) → annotate_status(failed/passing) → GraphIndex (stats)
→ build_subgraph (ranked G_MS) → render_slice (compact PromptSlice) → persist. Alpha/
Gamma consume the slice; CausalRank runs over the subgraph. Failing tests annotate +
rank the graph; they never define it. Pure; deterministic."""
from __future__ import annotations

import json
from pathlib import Path

from .rcc_mutation_graph import MutationGraph

_STATUSES = ("failed", "passing", "unknown_reachable")


def annotate_status(graph: MutationGraph, *, failed_ids: set,
                    passing_ids: "set | None" = None) -> MutationGraph:
    """Set every test vertex's status: failed (ran & failed), passing (ran & passed —
    ONLY when explicitly supplied), else unknown_reachable (reachable in GT but not
    known-run this RED suite). Chains mirror their test. In place; returns the graph."""
    failed_ids = set(failed_ids or ())
    passing_ids = set(passing_ids or ())
    for v in graph.vertices:
        if v.type in ("test", "assert"):
            v.status = ("failed" if v.fqn in failed_ids
                        else "passing" if v.fqn in passing_ids
                        else "unknown_reachable")
    by_fqn = {v.fqn: v.status for v in graph.vertices if v.type in ("test", "assert")}
    for c in graph.chains:
        c.status = by_fqn.get(c.test_fqn, "unknown_reachable")
    for e in graph.edges:
        if e.type == "TEST_ASSERTS":
            tv = graph.vertex(e.src)
            if tv is not None:
                e.test_status = tv.status
    return graph


def build_index(graph: MutationGraph) -> dict:
    """GraphIndex — the stats/summary of the FULL graph for the prompt header."""
    methods = [v for v in graph.vertices if v.type == "method"]
    tests = [v for v in graph.vertices if v.type in ("test", "assert")]
    status_counts = {s: sum(1 for v in tests if v.status == s) for s in _STATUSES}
    # callers ranked by how many chains pass through them
    through: dict = {}
    for c in graph.chains:
        for nid in c.node_ids:
            v = graph.vertex(nid)
            if v is not None and v.type == "method" and v.id != graph.target_id:
                through[v.fqn] = through.get(v.fqn, 0) + 1
    top_callers = [{"method": m, "chains": n}
                   for m, n in sorted(through.items(), key=lambda kv: (-kv[1], kv[0]))[:8]]
    edge_type_counts: dict = {}
    for e in graph.edges:
        edge_type_counts[e.type] = edge_type_counts.get(e.type, 0) + 1
    rtc: dict = {}
    for v in tests:
        cls = v.fqn.rsplit(".", 1)[0]
        rtc[cls] = rtc.get(cls, 0) + 1
    return {"target": graph.target_fqn,
            "method_count": len(methods), "test_count": len(tests),
            "edge_count": len(graph.edges),
            "chain_count": graph.stats.get("chain_count", len(graph.chains)),
            "distinct_tests": graph.stats.get("distinct_tests", len(tests)),
            "status_counts": status_counts, "top_callers": top_callers,
            "edge_type_counts": edge_type_counts, "reachable_test_classes": rtc}
