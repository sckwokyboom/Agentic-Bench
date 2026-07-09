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
    # callers ranked by how many DISTINCT chains pass through them (a method appearing
    # twice in one chain counts that chain ONCE — per-chain `seen` set)
    through: dict = {}
    for c in graph.chains:
        seen = set()
        for nid in c.node_ids:
            v = graph.vertex(nid)
            if v is not None and v.type == "method" and v.id != graph.target_id \
                    and v.fqn not in seen:
                seen.add(v.fqn)
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
    rtc_sorted = sorted(rtc.items(), key=lambda kv: (-kv[1], kv[0]))
    rtc_top = [{"class": c, "tests": n} for c, n in rtc_sorted[:5]]
    return {"target": graph.target_fqn,
            "method_count": len(methods), "test_count": len(tests),
            "edge_count": len(graph.edges),
            "chain_count": graph.stats.get("chain_count", len(graph.chains)),
            "distinct_tests": graph.stats.get("distinct_tests", len(tests)),
            "status_counts": status_counts, "top_callers": top_callers,
            "edge_type_counts": edge_type_counts, "reachable_test_classes": rtc,
            "reachable_test_classes_top": rtc_top,
            "other_reachable_test_classes": max(0, len(rtc) - len(rtc_top))}


def _is_direct_caller(graph, method_id) -> bool:
    return any(e.tgt == graph.target_id and e.src == method_id
               and e.type in ("CALLS", "DATA_DEP") for e in graph.edges)


def score_chains(graph: MutationGraph) -> list:
    """Deterministic per-chain score + selection_reason. No ML — a simple additive
    weight; the reason list matters more than the exact formula (Phase-3: k-medoid/HGT)."""
    has_dd = {pid for e in graph.edges if e.type == "DATA_DEP" for pid in e.path_ids}
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
    """GraphSubgraph / G_MS — the ranked analysis object (R3-lite: path k-medoid
    clustering for diversity, not top-K score). Keeps: target + direct
    callers/callees + ALL failed test ids (uncapped) + one representative medoid
    path per diversity cluster, with dropped_counts + per-path selection_reason.
    `k_failed`/`k_passing` are accepted for backward compatibility but no longer cap
    anything (failed is always uncapped; passing sizing is internal to
    cluster_chains) — only `k_unknown` is forwarded."""
    from .rcc_path_clusters import cluster_chains
    failed_ids = set(failed_ids or ())
    clustered = cluster_chains(graph, k_unknown=k_unknown)
    # kept paths = every forced (failed-status) chain + any chain whose test is in
    # the failed_ids param (covers callers that pass failed_ids without annotating
    # the graph first — the dead-param footgun) + each cluster's medoid.
    kept_ids = set(clustered["forced_paths"])
    kept_ids |= {c.id for c in graph.chains if c.test_fqn in failed_ids}
    for c in clustered["clusters"]:
        kept_ids.add(c["medoid_path_id"])
    kept_chains = [ch for ch in graph.chains if ch.id in kept_ids]

    def _reason(ch):
        if ch.status == "failed" or ch.test_fqn in failed_ids:
            return ["leads_to_failed_test"]
        cl = next((c for c in clustered["clusters"]
                   if c["medoid_path_id"] == ch.id), None)
        return cl["selection_reason"] if cl else ["kept"]

    kept = [{"path_id": ch.id, "test_fqn": ch.test_fqn, "status": ch.status,
            "node_ids": list(ch.node_ids), "selection_reason": _reason(ch)}
           for ch in kept_chains]
    # role classification: target / direct_caller / direct_callee / path_context.
    # focused_methods (contract subjects) = target + ALL direct callers/callees —
    # computed from the role sets DIRECTLY (never from a k_methods-capped list), so a
    # genuine direct caller can't be crowded out of the contract set by path-context
    # methods. path_context_methods (synopsis/join/assert-style upstream methods on the
    # kept chains) are labels, not contract subjects; only THEY are capped.
    direct_callers = {graph.vertex(e.src).fqn for e in graph.edges
                      if e.tgt == graph.target_id and e.type in ("CALLS", "DATA_DEP")
                      and graph.vertex(e.src) and graph.vertex(e.src).type == "method"}
    direct_callees = {graph.vertex(e.tgt).fqn for e in graph.edges
                      if e.src == graph.target_id and e.type == "CALLS"
                      and graph.vertex(e.tgt) and graph.vertex(e.tgt).type == "method"}
    direct_callers.discard(graph.target_fqn)
    direct_callees.discard(graph.target_fqn)

    def _role(fqn):
        if fqn == graph.target_fqn:
            return "target"
        if fqn in direct_callers:
            return "direct_caller"
        if fqn in direct_callees:
            return "direct_callee"
        return "path_context"

    # focused = target + every direct caller + every direct callee (uncapped)
    focused = ([{"fqn": graph.target_fqn, "role": "target"}]
               + [{"fqn": m, "role": "direct_caller"} for m in sorted(direct_callers)]
               + [{"fqn": m, "role": "direct_callee"} for m in sorted(direct_callees)
                  if m not in direct_callers])
    # path_context = other methods on kept chains (labels only), capped
    focused_fqns = {f["fqn"] for f in focused}
    path_context: list = []
    for ch in kept_chains:
        for nid in ch.node_ids:
            v = graph.vertex(nid)
            if v and v.type == "method" and v.fqn not in focused_fqns \
                    and v.fqn not in path_context:
                path_context.append(v.fqn)
    path_context = sorted(path_context)[:max(k_methods * 2, 20)]
    methods = [f["fqn"] for f in focused] + path_context   # back-compat / inspector
    # ALL failed ids (from annotated status) UNIONed with any caller-supplied
    # failed_ids — so a caller that forgot to annotate still gets the failed
    # frontier rather than silently empty (dead-param footgun).
    all_failed = sorted({v.fqn for v in graph.vertices
                         if v.type in ("test", "assert") and v.status == "failed"}
                        | failed_ids)

    sc = clustered["status_counts"]
    unknown_clusters = [c for c in clustered["clusters"]
                       if c["cluster_id"].startswith("unknown_reachable")]
    passing_clusters = [c for c in clustered["clusters"]
                       if c["cluster_id"].startswith("passing")]
    # "dropped" = chains not individually detailed as a kept path (failed is never
    # dropped; the rest are represented — but not individually shown — via their
    # cluster's summary/omitted_count).
    dropped = {"failed": 0,
              "unknown_reachable": max(0, sc.get("unknown_reachable", 0)
                                       - len(unknown_clusters)),
              "passing": max(0, sc.get("passing", 0) - len(passing_clusters))}
    frontier = {"failed": all_failed,
               "unknown_reachable_clusters": unknown_clusters,
               "passing_clusters": passing_clusters}
    return {"target": graph.target_fqn, "change_origin": graph.change_origin,
            "methods": methods, "test_frontier": frontier, "paths": kept,
            "clusters": clustered["clusters"], "forced_paths": clustered["forced_paths"],
            "selection_method": clustered["selection_method"],
            "dropped_counts": dropped,
            "focused_methods": focused, "path_context_methods": path_context}


def render_slice(graph: MutationGraph, subgraph: dict, index: dict) -> dict:
    """PromptSlice — the compact object Alpha/Gamma render. Carries the FULL-graph
    stats + dropped_counts + the omission note so the model can't infer that only the
    shown tests matter. Edges are typed objects (from/to/type/directions/status)."""
    keep_methods = set(subgraph["methods"])
    keep_tests = set(subgraph["test_frontier"]["failed"])
    for c in (subgraph["test_frontier"].get("unknown_reachable_clusters", [])
              + subgraph["test_frontier"].get("passing_clusters", [])):
        keep_tests.add(c["medoid_test"])
    methods = []
    for fqn in subgraph["methods"]:
        v = next((x for x in graph.vertices if x.type == "method" and x.fqn == fqn), None)
        methods.append({
            "fqn": fqn, "role": ("target" if fqn == graph.target_fqn else "caller_or_callee"),
            "signature": (v.l1_skeleton or {}).get("signature") if v else None,
            "source": v.source if v else None,
            "source_available_from_workdir": bool(v and v.source is None
                                                  and fqn == graph.target_fqn)})
    edges = []
    for e in graph.edges:
        sfqn = (graph.vertex(e.src) or None) and graph.vertex(e.src).fqn
        tfqn = (graph.vertex(e.tgt) or None) and graph.vertex(e.tgt).fqn
        if (sfqn in keep_methods or sfqn in keep_tests) and \
           (tfqn in keep_methods or tfqn in keep_tests):
            edges.append({"from": e.src, "to": e.tgt, "type": e.type,
                          "structural_direction": e.structural_direction,
                          "influence_direction": e.influence_direction,
                          "path_count": len(e.path_ids),
                          "sample_path_ids": list(e.path_ids)[:5],
                          "omitted_path_ids_count": max(0, len(e.path_ids) - 5),
                          "test_status": e.test_status})
    total_tests = index["test_count"]
    shown = len(keep_tests)
    n_clusters = (len(subgraph["test_frontier"].get("unknown_reachable_clusters", []))
                 + len(subgraph["test_frontier"].get("passing_clusters", [])))
    note = (f"This is a RANKED SLICE of a larger mutation graph: {index['method_count']} "
            f"methods, {index['distinct_tests']} reachable tests, {index['chain_count']} "
            f"call chains. Showing {len(subgraph['methods'])} methods and {shown} of "
            f"{total_tests} tests (all {len(subgraph['test_frontier']['failed'])} failed "
            f"+ {n_clusters} cluster medoids). Omitted tests/paths are NOT necessarily "
            f"irrelevant — dropped_counts records what was left out. Influence flows "
            f"method→test (a method's behaviour influences the tests that assert it), "
            f"the reverse of the structural call direction.")
    return {"target": graph.target_fqn, "change_origin": graph.change_origin,
            "source_graph_stats": {k: index[k] for k in
                ("method_count", "test_count", "distinct_tests", "chain_count",
                 "edge_count", "status_counts", "top_callers")},
            "methods": methods, "edges": edges,
            "test_frontier": subgraph["test_frontier"],
            "paths": subgraph["paths"], "clusters": subgraph["clusters"],
            "selection_method": subgraph["selection_method"],
            "dropped_counts": subgraph["dropped_counts"],
            "omission_note": note}


def render_prompt_slice(graph: MutationGraph, subgraph: dict, index: dict) -> dict:
    """PromptSlice v2 — the compact, bounded MODEL CONTRACT Alpha/Gamma render (NOT the
    inspector object). focused_methods (contract subjects) = target + direct callers/
    callees, with source; path-context methods are labels; one cluster block (no
    member_ids); collapsed edges; top-N index; run-length-compressed shapes."""
    tfqn = graph.target_fqn
    src_by_fqn = {v.fqn: v for v in graph.vertices if v.type == "method"}

    focused = []
    for m in subgraph.get("focused_methods", []):
        v = src_by_fqn.get(m["fqn"])
        sig = (v.l1_skeleton or {}).get("signature") if v else None
        body = v.source if v else None
        focused.append({"fqn": m["fqn"], "role": m["role"], "signature": sig,
                        "source": body,
                        "source_from_workdir": (m["role"] == "target" and body is None)})

    frontier = subgraph.get("test_frontier", {})
    clusters = []
    for c in frontier.get("unknown_reachable_clusters", []):
        clusters.append({"cluster_id": c["cluster_id"], "size": c["size"],
                         "medoid_test": c["medoid_test"], "path_shape": c["path_shape"],
                         "nearest_examples": c.get("nearest_examples", [])[:3],
                         "sample_member_ids": (c.get("member_ids") or [])[:3],
                         "omitted_member_ids_count": max(0, c["size"]
                                                         - len((c.get("member_ids") or [])[:3]))})

    # collapse CALLS/DATA_DEP between the same (from,to), among focused methods only
    fset = {m["fqn"] for m in focused}
    coll: dict = {}
    for e in graph.edges:
        s = graph.vertex(e.src); t = graph.vertex(e.tgt)
        sf = s.fqn if s else e.src; tf = t.fqn if t else e.tgt
        if sf in fset and tf in fset and e.type in ("CALLS", "DATA_DEP"):
            key = (e.src, e.tgt)
            d = coll.setdefault(key, {"from": e.src, "to": e.tgt, "edge_types": [],
                                      "structural_direction": e.structural_direction,
                                      "influence_direction": e.influence_direction,
                                      "path_count": 0, "sample_path_ids": []})
            if e.type not in d["edge_types"]:
                d["edge_types"].append(e.type)
            d["path_count"] += len(e.path_ids)
            for pid in e.path_ids:
                if len(d["sample_path_ids"]) < 3 and pid not in d["sample_path_ids"]:
                    d["sample_path_ids"].append(pid)
    compact_edges = []
    for d in coll.values():
        d["omitted_path_ids_count"] = max(0, d["path_count"] - len(d["sample_path_ids"]))
        compact_edges.append(d)

    s = index
    summary = {"methods": s["method_count"], "tests": s["test_count"],
               "chains": s["chain_count"], "edges": s["edge_count"],
               "status": s["status_counts"],
               "reachable_test_classes_top": s.get("reachable_test_classes_top", []),
               "other_reachable_test_classes": s.get("other_reachable_test_classes", 0),
               "top_callers": s["top_callers"][:5]}
    dc = subgraph.get("dropped_counts", {})
    selection = {"method": subgraph.get("selection_method", "path_k_medoids_weighted_lcs"),
                 "shown_failed_tests": len(frontier.get("failed", [])),
                 "shown_unknown_clusters": len(clusters),
                 "shown_focused_methods": len(focused), "dropped": dc}
    note = (f"RANKED SLICE of a {summary['methods']}-method / {summary['tests']}-test / "
            f"{summary['chains']}-chain graph. focused_methods are the ONLY contract "
            f"subjects (target + direct callers/callees); path_context_methods and the "
            f"path clusters are STRUCTURAL REFERENCE — do NOT write contracts for them. "
            f"Omitted tests/paths are not necessarily irrelevant. Influence flows "
            f"method→test (reverse of the call direction).")
    ps = {"schema": "rcc.prompt_slice.v2", "target": tfqn,
          "change_origin": graph.change_origin, "source_graph_summary": summary,
          "selection_summary": selection, "focused_methods": focused,
          "path_context_methods": subgraph.get("path_context_methods", []),
          "failed_tests": frontier.get("failed", []),
          "representative_path_clusters": clusters, "compact_edges": compact_edges,
          "omission_note": note}
    blob = json.dumps(ps)
    ps["prompt_slice_stats"] = {"chars": len(blob), "approx_tokens": len(blob) // 4,
                                "focused_methods": len(focused),
                                "edges": len(compact_edges), "clusters": len(clusters)}
    return ps


def _graph_to_dict(graph: MutationGraph) -> dict:
    return {"target": graph.target_fqn, "change_origin": graph.change_origin,
            "stats": graph.stats,
            "vertices": [{"id": v.id, "type": v.type, "fqn": v.fqn,
                          "is_changed": v.is_changed, "status": v.status,
                          "location": v.location} for v in graph.vertices],
            "edges": [{"from": e.src, "to": e.tgt, "type": e.type,
                       "structural_direction": e.structural_direction,
                       "influence_direction": e.influence_direction,
                       "path_ids": e.path_ids, "test_status": e.test_status}
                      for e in graph.edges],
            "chains": [{"id": c.id, "test_fqn": c.test_fqn, "status": c.status,
                        "node_ids": c.node_ids} for c in graph.chains]}


def persist(out_dir, graph, index, subgraph, slice_, *, prompt_slice=None) -> None:
    """Write the graph layers for inspection / the future trace-visualizer, plus the
    compact prompt_slice.json (v2 model contract) when supplied. Best-effort."""
    try:
        d = Path(out_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / "raw.json").write_text(json.dumps(_graph_to_dict(graph), indent=1))
        (d / "index.json").write_text(json.dumps(index, indent=1))
        (d / "subgraph.json").write_text(json.dumps(subgraph, indent=1))
        (d / "slice.json").write_text(json.dumps(slice_, indent=1))
        (d / "clusters.json").write_text(json.dumps({
            "selection_method": subgraph.get("selection_method"),
            "forced_paths": subgraph.get("forced_paths"),
            "clusters": subgraph.get("clusters")}, indent=1))
        if prompt_slice is not None:
            (d / "prompt_slice.json").write_text(json.dumps(prompt_slice, indent=1))
    except OSError:
        pass
