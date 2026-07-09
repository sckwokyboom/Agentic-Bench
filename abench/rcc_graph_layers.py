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


def _is_direct_caller(graph, method_id) -> bool:
    return any(e.tgt == graph.target_id and e.src == method_id
               and e.type in ("CALLS", "DATA_DEP") for e in graph.edges)


def score_chains(graph: MutationGraph) -> list:
    """Deterministic per-chain score + selection_reason. No ML — a simple additive
    weight; the reason list matters more than the exact formula (Phase-3: k-medoid/HGT)."""
    has_dd = {e.type == "DATA_DEP" and pid for e in graph.edges for pid in e.path_ids}
    out = []
    for c in graph.chains:
        reasons, score = [], 0
        if c.status == "failed":
            score += 100; reasons.append("leads_to_failed_test")
        elif c.status == "passing":
            score += 20; reasons.append("covered_by_red_run")
        # direct caller path (chain reaches target via a direct caller)
        mids = [n for n in c.node_ids if (graph.vertex(n) or None)
                and graph.vertex(n).type == "method" and n != graph.target_id]
        if any(_is_direct_caller(graph, m) for m in mids):
            score += 50; reasons.append("direct_caller_path")
        if c.id in has_dd:
            score += 30; reasons.append("data_dep")
        score -= max(0, len(c.node_ids) - 2) * 5      # distance penalty
        reasons.append("shortest_path" if len(c.node_ids) <= 2 else "longer_path")
        out.append({"path_id": c.id, "test_fqn": c.test_fqn, "status": c.status,
                    "score": score, "nodes": list(c.node_ids),
                    "selection_reason": reasons})
    out.sort(key=lambda s: (-s["score"], s["path_id"]))
    return out


def build_subgraph(graph: MutationGraph, *, failed_ids: "set | None" = None,
                   k_failed: int = 12, k_passing: int = 5, k_unknown: int = 5,
                   k_methods: int = 8) -> dict:
    """GraphSubgraph / G_MS — the ranked analysis object. Keeps: target + direct
    callers/callees + ALL failed test ids + top-K paths per status bucket, with
    dropped_counts + per-path selection_reason."""
    scored = score_chains(graph)
    buckets: dict = {"failed": [], "passing": [], "unknown_reachable": []}
    for s in scored:
        buckets.get(s["status"], buckets["unknown_reachable"]).append(s)
    caps = {"failed": k_failed, "passing": k_passing, "unknown_reachable": k_unknown}
    kept, dropped = [], {}
    for st, items in buckets.items():
        kept += items[:caps[st]]
        dropped[st] = max(0, len(items) - caps[st])
    # methods: target + direct callers/callees + any method on a kept path
    methods = {graph.target_fqn}
    for e in graph.edges:
        if e.tgt == graph.target_id and e.type in ("CALLS", "DATA_DEP"):
            v = graph.vertex(e.src)
            if v and v.type == "method":
                methods.add(v.fqn)
        if e.src == graph.target_id and e.type == "CALLS":
            v = graph.vertex(e.tgt)
            if v and v.type == "method":
                methods.add(v.fqn)
    for s in kept:
        for nid in s["nodes"]:
            v = graph.vertex(nid)
            if v and v.type == "method":
                methods.add(v.fqn)
    methods = ([graph.target_fqn]
               + sorted(m for m in methods if m != graph.target_fqn))[:k_methods]
    all_failed = sorted({v.fqn for v in graph.vertices
                         if v.type in ("test", "assert") and v.status == "failed"})
    frontier = {
        "failed": all_failed,
        "passing_sample": [s["test_fqn"] for s in buckets["passing"][:k_passing]],
        "unknown_reachable_sample": [s["test_fqn"]
                                     for s in buckets["unknown_reachable"][:k_unknown]]}
    return {"target": graph.target_fqn, "change_origin": graph.change_origin,
            "methods": methods, "test_frontier": frontier, "paths": kept,
            "dropped_counts": dropped}
