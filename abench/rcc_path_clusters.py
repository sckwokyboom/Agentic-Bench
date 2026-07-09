"""RapidCausalCoder R3-lite — path-level k-medoid clustering.

The mutational subgraph's REPRESENTATIVE paths come from clustering the call chains
(one chain = one data point) by weighted-LCS distance and picking a real medoid per
cluster — so Alpha/Gamma see the DIFFERENT usage scenarios (direct addRowValues vs a
deep help-rendering chain), not top-K near-duplicates. Deterministic; dependency-free
(greedy farthest-first + medoid refinement, not PAM). k-medoid = diversity; the R2
deterministic score is only a within-cluster priority. Spec: Revision R3-lite."""
from __future__ import annotations

import math

# node-role weights so a shared "…→target" suffix does not collapse every path
_W_TARGET = 0.1
_W_DIRECT_CALLER = 0.5
_W_UPSTREAM = 1.0
_W_TEST = 0.7


def _simple(fqn: str) -> str:
    return fqn.rsplit(".", 1)[-1].split("$")[-1]


def _direct_callers(graph) -> set:
    return {e.src for e in graph.edges if e.tgt == graph.target_id
            and e.type in ("CALLS", "DATA_DEP")}


def normalize_chain(graph, chain) -> list:
    """A chain → [(label, weight)] test-first. Labels are simple names; weights encode
    role (target low, direct caller medium, upstream high, test node)."""
    callers = _direct_callers(graph)
    out = []
    for nid in chain.node_ids:
        v = graph.vertex(nid)
        if v is None:
            out.append((nid, _W_UPSTREAM)); continue
        if v.type in ("test", "assert"):
            out.append((f"test:{v.fqn.rsplit('.', 1)[0]}", _W_TEST))
        elif nid == graph.target_id:
            out.append((_simple(v.fqn), _W_TARGET))
        elif nid in callers:
            out.append((_simple(v.fqn), _W_DIRECT_CALLER))
        else:
            out.append((_simple(v.fqn), _W_UPSTREAM))
    return out


def _wlen(seq) -> float:
    return sum(w for _, w in seq) or 1.0


def weighted_lcs_distance(a, b) -> float:
    """1 − 2·wLCS/(w(a)+w(b)); labels match on equality, matched weight = the MEAN of
    the two sides' weights so the distance is SYMMETRIC (d(a,b)==d(b,a)) — greedy_kmedoids
    assumes symmetry. 0 identical, →1 disjoint."""
    if not a or not b:
        return 1.0
    la, lb = [x[0] for x in a], [x[0] for x in b]
    wa, wb = [x[1] for x in a], [x[1] for x in b]
    # weighted LCS DP; a matched label contributes the mean of its two role-weights
    dp = [[0.0] * (len(lb) + 1) for _ in range(len(la) + 1)]
    for i in range(1, len(la) + 1):
        for j in range(1, len(lb) + 1):
            if la[i - 1] == lb[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + (wa[i - 1] + wb[j - 1]) / 2.0
            else:
                dp[i][j] = dp[i - 1][j] if dp[i - 1][j] >= dp[i][j - 1] else dp[i][j - 1]
    wlcs = dp[len(la)][len(lb)]
    d = 1.0 - 2.0 * wlcs / (_wlen(a) + _wlen(b))
    return max(0.0, min(1.0, d))


def _test_class(chain) -> str:
    return chain.test_fqn.rsplit(".", 1)[0]


def _edge_types(graph, chain) -> set:
    types = set()
    ids = chain.node_ids
    for k in range(len(ids) - 1):
        for e in graph.edges:
            if e.src == ids[k] and e.tgt == ids[k + 1]:
                types.add(e.type)
    types.add("TEST_ASSERTS")
    return types


def chain_distance(graph, ca, cb, *, _cache: "dict | None" = None) -> float:
    """0.7·weighted_lcs + 0.2·test_class_distance + 0.1·edge_type_jaccard.

    `_cache` (optional, keyed by chain.id) memoizes normalize_chain/_edge_types —
    both pure functions of a single chain — so callers doing many pairwise
    comparisons (greedy_kmedoids) don't recompute the same O(chain_len·edge_count)
    work per chain on every pair. Without a cache, behaves exactly as before."""
    def _per_chain(chain):
        if _cache is None:
            return normalize_chain(graph, chain), _edge_types(graph, chain)
        hit = _cache.get(chain.id)
        if hit is None:
            hit = (normalize_chain(graph, chain), _edge_types(graph, chain))
            _cache[chain.id] = hit
        return hit

    na, ea = _per_chain(ca)
    nb, eb = _per_chain(cb)
    seq = weighted_lcs_distance(na, nb)
    tcd = 0.0 if _test_class(ca) == _test_class(cb) else 1.0
    jac = 1.0 - (len(ea & eb) / len(ea | eb) if (ea | eb) else 1.0)
    return 0.7 * seq + 0.2 * tcd + 0.1 * jac


def greedy_kmedoids(items: list, distfn, k: int) -> list:
    """Deterministic greedy k-medoids: farthest-first init + assign + medoid refine
    (refinement scan capped at 200 members). `distfn(i, j)` symmetric. Returns
    [{medoid, members}]. If len(items) <= k → singleton clusters."""
    items = list(items)
    if k <= 0:
        return []
    if len(items) <= k:
        return [{"medoid": it, "members": [it]} for it in items]
    first = min(items, key=lambda it: (sum(distfn(it, o) for o in items[:50]), str(it)))
    medoids = [first]
    while len(medoids) < k:
        cand = max(items, key=lambda it: (min(distfn(it, m) for m in medoids), str(it)))
        if cand in medoids:
            break
        medoids.append(cand)
    clusters = {id(m): {"medoid": m, "members": []} for m in medoids}
    mlist = list(medoids)
    for it in items:
        nearest = min(mlist, key=lambda m: (distfn(it, m), str(m)))
        clusters[id(nearest)]["members"].append(it)
    out = []
    for c in clusters.values():
        mem = c["members"] or [c["medoid"]]
        scan = mem if len(mem) <= 200 else mem[:200]
        medoid = min(mem, key=lambda x: (sum(distfn(x, o) for o in scan), str(x)))
        out.append({"medoid": medoid, "members": mem})
    return out


def compress_shape(labels: list) -> str:
    """Run-length compress a path's node labels: [a,a,b] -> 'a×2 → b'."""
    out, i = [], 0
    while i < len(labels):
        j = i
        while j + 1 < len(labels) and labels[j + 1] == labels[i]:
            j += 1
        n = j - i + 1
        out.append(f"{labels[i]}×{n}" if n > 1 else labels[i])
        i = j + 1
    return " → ".join(out)


def _k_for(n: int) -> int:
    return min(8, max(3, round(math.sqrt(n) / 5))) if n > 0 else 0


def cluster_chains(graph, *, k_unknown: "int | None" = None) -> dict:
    """Status-bucketed path clustering. failed = force-include all; unknown_reachable =
    k-medoid; passing = k-medoid if present. Returns cluster summaries + forced ids."""
    by_status: dict = {"failed": [], "passing": [], "unknown_reachable": []}
    for c in graph.chains:
        by_status.get(c.status or "unknown_reachable",
                      by_status["unknown_reachable"]).append(c)
    forced = [c.id for c in by_status["failed"]]
    _cache: dict = {}          # shared across buckets — normalize_chain/_edge_types memo
    # R3-lite: k-medoid gives DIVERSITY; the R2 deterministic score is demoted to a
    # WITHIN-cluster PRIORITY signal (tie-break example ordering + a top-scored pick),
    # not the diversity mechanism.
    from .rcc_graph_layers import score_chains
    _score = {s["path_id"]: s["score"] for s in score_chains(graph)}

    def summarize(bucket_name, chains, k):
        if not chains:
            return []
        clusters = greedy_kmedoids(
            chains, lambda a, b: chain_distance(graph, a, b, _cache=_cache), k)
        out = []
        for i, cl in enumerate(clusters):
            med = cl["medoid"]
            shape = compress_shape([lbl for lbl, _ in normalize_chain(graph, med)])
            # nearest to the medoid, ties broken by higher within-cluster score
            examples = sorted(cl["members"],
                              key=lambda x: (chain_distance(graph, x, med, _cache=_cache),
                                             -_score.get(x.id, 0), x.id))[:3]
            top = max(cl["members"], key=lambda x: (_score.get(x.id, 0), x.id))
            # cluster_quality — how tight the cluster is around its medoid (diagnostics
            # only; clusters.json via persist, NEVER the v2 prompt slice — that stays
            # lean). Empty/singleton clusters have nothing to spread from -> 0.0.
            dists = [chain_distance(graph, m, med, _cache=_cache) for m in cl["members"]]
            avg_d = round(sum(dists) / len(dists), 3) if dists else 0.0
            max_d = round(max(dists), 3) if dists else 0.0
            out.append({
                "cluster_id": f"{bucket_name}_{i}", "size": len(cl["members"]),
                "medoid_path_id": med.id, "medoid_test": med.test_fqn,
                "top_scored_test": top.test_fqn,
                "path_shape": shape, "status_mix": {bucket_name: len(cl["members"])},
                "member_ids": [m.id for m in cl["members"]],
                "nearest_examples": [e.test_fqn for e in examples],
                "omitted_count": max(0, len(cl["members"]) - len(examples)),
                "cluster_quality": {"avg_distance_to_medoid": avg_d,
                                    "max_distance_to_medoid": max_d},
                "selection_reason": ["k_medoid_representative", f"bucket:{bucket_name}"]})
        return out

    ku = k_unknown if k_unknown is not None else _k_for(len(by_status["unknown_reachable"]))
    clusters = (summarize("unknown_reachable", by_status["unknown_reachable"], ku)
                + summarize("passing", by_status["passing"],
                            _k_for(len(by_status["passing"]))))
    return {"selection_method": "path_k_medoids_weighted_lcs",
            "k_unknown": ku, "forced_paths": forced, "clusters": clusters,
            "status_counts": {s: len(v) for s, v in by_status.items()}}
