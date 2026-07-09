# RapidCausalCoder R3-lite — path k-medoid clustering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace top-K-by-score path selection with path-level k-medoid clustering (representativeness). One data point = one chain; weighted-LCS distance; status buckets (failed force-included, unknown_reachable clustered); a `clusters.json` layer; the PromptSlice renders cluster summaries (medoid + shape + size) and edges carry `path_count`/`sample_path_ids`/`omitted` instead of full `path_ids` arrays. Deterministic score is demoted to within-cluster priority.

**Architecture:** New `abench/rcc_path_clusters.py` (distance + greedy k-medoids + cluster_chains). `build_subgraph`/`render_slice`/`persist` (in `rcc_graph_layers.py`) consume it. Alpha/Gamma render the cluster summaries. `score_chains` stays but is used only to pick a cluster's top-scored example. Dependency-free; deterministic.

**Tech Stack:** Python 3.11+, pytest. No new deps.

Spec: `docs/superpowers/specs/2026-07-08-rapidcausalcoder-mvp-design.md` — **Revision R3-lite**.

---

## File Structure
- Create: `abench/rcc_path_clusters.py` — normalize_chain, weighted_lcs_distance, chain_distance, greedy_kmedoids, cluster_chains.
- Modify: `abench/rcc_graph_layers.py` — build_subgraph (use cluster_chains), render_slice (cluster summaries + edge path sampling), persist (clusters.json).
- Modify: `abench/rcc_prompts.py` — render `*_clusters` in the frontier block.
- Modify: `abench/rcc_graph.py` / `rcc_orchestrate.py` — only if the slice/subgraph dict keys they read change (frontier key rename); adjust minimally.
- Tests: create `tests/test_rcc_path_clusters.py`; extend `tests/test_rcc_graph_layers.py`, `tests/test_rcc_prompts.py`.

DO NOT touch unrelated worktree changes. Full suite OOMs — run `-k` subsets. Known pre-existing unrelated failure: `tests/test_robustness.py::test_workdir_cleaned_up_when_client_raises`.

---

### Task 1: `rcc_path_clusters.py` — distance + greedy k-medoids + cluster_chains

**Files:** Create `abench/rcc_path_clusters.py`; Test `tests/test_rcc_path_clusters.py`.

- [ ] **Step 1: Write tests**

```python
# tests/test_rcc_path_clusters.py
from abench.rcc_mutation_graph import MgChain, MgEdge, MgVertex, MutationGraph
from abench.rcc_path_clusters import (chain_distance, cluster_chains,
                                      greedy_kmedoids, normalize_chain,
                                      weighted_lcs_distance)


def _g():
    # target put; direct caller addRow; upstream join/synopsis; several tests
    vs = [MgVertex(id="method:C.put", type="method", fqn="C.put", is_changed=True),
          MgVertex(id="method:C.addRow", type="method", fqn="C.addRow"),
          MgVertex(id="method:H.join", type="method", fqn="H.join"),
          MgVertex(id="method:H.syn", type="method", fqn="H.syn")]
    tests = ["HT.a1", "HT.a2", "HT.a3", "HT.join1", "HT.syn1"]
    for t in tests:
        vs.append(MgVertex(id=f"test:{t}", type="test", fqn=f"picocli.{t}"))
    es = [MgEdge(src="method:C.addRow", tgt="method:C.put", type="CALLS")]  # addRow direct caller
    # chains: three near-identical direct addRow paths, one join path, one synopsis path
    chains = [
        MgChain(id="p1", test_fqn="picocli.HT.a1",
                node_ids=["test:HT.a1", "method:C.addRow", "method:C.put"]),
        MgChain(id="p2", test_fqn="picocli.HT.a2",
                node_ids=["test:HT.a2", "method:C.addRow", "method:C.put"]),
        MgChain(id="p3", test_fqn="picocli.HT.a3",
                node_ids=["test:HT.a3", "method:C.addRow", "method:C.put"]),
        MgChain(id="p4", test_fqn="picocli.HT.join1",
                node_ids=["test:HT.join1", "method:H.join", "method:C.addRow", "method:C.put"]),
        MgChain(id="p5", test_fqn="picocli.HT.syn1",
                node_ids=["test:HT.syn1", "method:H.syn", "method:H.join",
                          "method:C.addRow", "method:C.put"]),
    ]
    return MutationGraph(target_id="method:C.put", vertices=vs, edges=es, chains=chains)


def test_weighted_lcs_distance_bounds():
    g = _g()
    a = normalize_chain(g, g.chains[0])
    assert weighted_lcs_distance(a, a) == 0.0                 # identical
    b = normalize_chain(g, g.chains[3])                        # shared …addRow→put suffix
    d = weighted_lcs_distance(a, b)
    assert 0.0 < d < 1.0                                       # similar but not identical
    # disjoint sequences → ~1
    x = [("z1", 1.0), ("z2", 1.0)]
    assert weighted_lcs_distance(x, a) > 0.9


def test_greedy_kmedoids_returns_k_clusters_and_real_medoids():
    items = list("abcdef")
    dist = lambda i, j: 0.0 if i == j else abs(ord(i) - ord(j)) / 10
    clusters = greedy_kmedoids(items, dist, 3)
    assert len(clusters) == 3
    assert all(c["medoid"] in items for c in clusters)        # medoids are real items
    assert sum(len(c["members"]) for c in clusters) == len(items)


def test_cluster_chains_separates_direct_from_deep_paths():
    g = _g()
    from abench.rcc_graph_layers import annotate_status
    annotate_status(g, failed_ids={"picocli.HT.a1"})          # p1 failed; rest unknown
    res = cluster_chains(g, k_unknown=2)
    assert res["forced_paths"] == ["p1"]                      # failed force-included
    clusters = res["clusters"]
    assert len(clusters) >= 2
    # the deep synopsis path (p5) and a direct addRow path (p2/p3) are NOT in the same cluster
    def cluster_of(pid):
        return next(c["cluster_id"] for c in clusters if pid in c["member_ids"])
    assert cluster_of("p5") != cluster_of("p2")
    # each cluster summary carries a real medoid path + a readable shape
    c0 = clusters[0]
    assert c0["medoid_path_id"] in {"p2", "p3", "p4", "p5"}
    assert "put" in c0["path_shape"] and "→" in c0["path_shape"]
    assert c0["size"] >= 1 and "selection_reason" in c0
```

- [ ] **Step 2: Run** → FAIL (module missing).

- [ ] **Step 3: Implement `abench/rcc_path_clusters.py`**

```python
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
    """1 − 2·wLCS/(w(a)+w(b)); labels match on equality, matched weight = a's weight.
    0 identical, →1 disjoint."""
    if not a or not b:
        return 1.0
    la, lb = [x[0] for x in a], [x[0] for x in b]
    wa = [x[1] for x in a]
    # weighted LCS DP
    dp = [[0.0] * (len(lb) + 1) for _ in range(len(la) + 1)]
    for i in range(1, len(la) + 1):
        for j in range(1, len(lb) + 1):
            if la[i - 1] == lb[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + wa[i - 1]
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


def chain_distance(graph, ca, cb) -> float:
    """0.7·weighted_lcs + 0.2·test_class_distance + 0.1·edge_type_jaccard."""
    seq = weighted_lcs_distance(normalize_chain(graph, ca), normalize_chain(graph, cb))
    tcd = 0.0 if _test_class(ca) == _test_class(cb) else 1.0
    ta, tb = _edge_types(graph, ca), _edge_types(graph, cb)
    jac = 1.0 - (len(ta & tb) / len(ta | tb) if (ta | tb) else 1.0)
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

    def summarize(bucket_name, chains, k):
        if not chains:
            return []
        clusters = greedy_kmedoids(chains, lambda a, b: chain_distance(graph, a, b), k)
        out = []
        for i, cl in enumerate(clusters):
            med = cl["medoid"]
            shape = " → ".join(lbl for lbl, _ in normalize_chain(graph, med))
            examples = sorted(cl["members"],
                              key=lambda x: (chain_distance(graph, x, med), x.id))[:3]
            out.append({
                "cluster_id": f"{bucket_name}_{i}", "size": len(cl["members"]),
                "medoid_path_id": med.id, "medoid_test": med.test_fqn,
                "path_shape": shape, "status_mix": {bucket_name: len(cl["members"])},
                "member_ids": [m.id for m in cl["members"]],
                "nearest_examples": [e.test_fqn for e in examples],
                "omitted_count": max(0, len(cl["members"]) - len(examples)),
                "selection_reason": ["k_medoid_representative", f"bucket:{bucket_name}"]})
        return out

    ku = k_unknown if k_unknown is not None else _k_for(len(by_status["unknown_reachable"]))
    clusters = (summarize("unknown_reachable", by_status["unknown_reachable"], ku)
                + summarize("passing", by_status["passing"],
                            _k_for(len(by_status["passing"]))))
    return {"selection_method": "path_k_medoids_weighted_lcs",
            "k_unknown": ku, "forced_paths": forced, "clusters": clusters,
            "status_counts": {s: len(v) for s, v in by_status.items()}}
```

- [ ] **Step 4: Run** `python3 -m pytest tests/test_rcc_path_clusters.py -q` → 3 pass.

- [ ] **Step 5: Commit**
```bash
git add abench/rcc_path_clusters.py tests/test_rcc_path_clusters.py
git commit -m "feat(rcc): R3-lite path k-medoid clustering — weighted-LCS distance + greedy medoids (diversity)"
```

---

### Task 2: build_subgraph + render_slice + persist use clusters

**Files:** Modify `abench/rcc_graph_layers.py`; Test `tests/test_rcc_graph_layers.py` (append).

- [ ] **Step 1: Append tests**

```python
def test_build_subgraph_uses_clusters_and_keeps_all_failed():
    from abench.rcc_graph_layers import annotate_status, build_subgraph
    from abench.rcc_mutation_graph import MgChain, MgEdge, MgVertex, MutationGraph
    vs = [MgVertex(id="method:C.put", type="method", fqn="C.put", is_changed=True),
          MgVertex(id="method:C.addRow", type="method", fqn="C.addRow"),
          MgVertex(id="method:H.syn", type="method", fqn="H.syn")]
    for t in ("HT.f1", "HT.u1", "HT.u2", "HT.u3", "TT.u4"):
        vs.append(MgVertex(id=f"test:{t}", type="test", fqn=f"picocli.{t}"))
    es = [MgEdge(src="method:C.addRow", tgt="method:C.put", type="CALLS")]
    chains = [MgChain(id="p0", test_fqn="picocli.HT.f1",
                      node_ids=["test:HT.f1", "method:C.addRow", "method:C.put"])]
    for i, t in enumerate(("HT.u1", "HT.u2", "HT.u3", "TT.u4"), 1):
        seq = (["test:" + t, "method:C.addRow", "method:C.put"] if i < 3
               else ["test:" + t, "method:H.syn", "method:C.addRow", "method:C.put"])
        chains.append(MgChain(id=f"p{i}", test_fqn=f"picocli.{t}", node_ids=seq))
    g = MutationGraph(target_id="method:C.put", vertices=vs, edges=es, chains=chains)
    annotate_status(g, failed_ids={"picocli.HT.f1"})
    gs = build_subgraph(g, failed_ids={"picocli.HT.f1"}, k_unknown=2)
    assert gs["test_frontier"]["failed"] == ["picocli.HT.f1"]     # all failed kept
    assert "unknown_reachable_clusters" in gs["test_frontier"]     # clusters, not flat sample
    cl = gs["test_frontier"]["unknown_reachable_clusters"]
    assert len(cl) >= 2 and all("path_shape" in c and "medoid_test" in c for c in cl)
    assert gs["selection_method"] == "path_k_medoids_weighted_lcs"


def test_render_slice_edges_sample_path_ids_not_full():
    from abench.rcc_graph_layers import (annotate_status, build_index, build_subgraph,
                                         render_slice)
    from abench.rcc_mutation_graph import MgChain, MgEdge, MgVertex, MutationGraph
    e = MgEdge(src="test:T.a", tgt="method:C.put", type="TEST_ASSERTS",
               path_ids=[f"p{i}" for i in range(12)])
    g = MutationGraph(
        target_id="method:C.put",
        vertices=[MgVertex(id="method:C.put", type="method", fqn="C.put", is_changed=True),
                  MgVertex(id="test:T.a", type="test", fqn="p.T.a")],
        edges=[e], chains=[MgChain(id="p0", test_fqn="p.T.a",
                                   node_ids=["test:T.a", "method:C.put"])])
    annotate_status(g, failed_ids={"p.T.a"})
    sl = render_slice(g, build_subgraph(g, failed_ids={"p.T.a"}), build_index(g))
    edge = sl["edges"][0]
    assert "path_ids" not in edge                        # full array gone
    assert edge["path_count"] == 12 and len(edge["sample_path_ids"]) <= 5
    assert edge["omitted_path_ids_count"] == 12 - len(edge["sample_path_ids"])
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** — in `abench/rcc_graph_layers.py`:

1. `build_subgraph`: replace the top-K bucket slicing with `cluster_chains`. Keep the deterministic `score_chains` only to attach a top-scored example inside each cluster (optional). New body sketch (keep the signature + the `methods` selection + `dropped_counts`):

```python
    from .rcc_path_clusters import cluster_chains
    clustered = cluster_chains(graph, k_unknown=None)
    # kept paths = all failed (forced) + each cluster's medoid
    kept_ids = set(clustered["forced_paths"])
    for c in clustered["clusters"]:
        kept_ids.add(c["medoid_path_id"])
    kept = [ch for ch in graph.chains if ch.id in kept_ids]
    # methods: target + direct callers/callees + any method on a kept path (unchanged loop)
    ...  # (keep the existing methods-selection loop, iterating `kept` node_ids)
    all_failed = sorted({v.fqn for v in graph.vertices
                         if v.type in ("test", "assert") and v.status == "failed"}
                        | set(failed_ids or ()))
    sc = clustered["status_counts"]
    dropped = {"unknown_reachable": max(0, sc.get("unknown_reachable", 0)
                                        - sum(c["size"] for c in clustered["clusters"]
                                              if c["cluster_id"].startswith("unknown"))),
               "passing": 0, "failed": 0}
    frontier = {"failed": all_failed,
                "unknown_reachable_clusters": [c for c in clustered["clusters"]
                                               if c["cluster_id"].startswith("unknown")],
                "passing_clusters": [c for c in clustered["clusters"]
                                     if c["cluster_id"].startswith("passing")]}
    return {"target": graph.target_fqn, "change_origin": graph.change_origin,
            "methods": methods, "test_frontier": frontier, "paths": kept,
            "clusters": clustered["clusters"], "forced_paths": clustered["forced_paths"],
            "selection_method": clustered["selection_method"],
            "dropped_counts": dropped}
```

2. `render_slice`: the frontier now carries clusters; keep_tests = failed ids + each cluster's medoid_test. Edges: drop `path_ids`, add `path_count`/`sample_path_ids`(≤5)/`omitted_path_ids_count`:

```python
    keep_tests = set(subgraph["test_frontier"]["failed"])
    for c in (subgraph["test_frontier"].get("unknown_reachable_clusters", [])
              + subgraph["test_frontier"].get("passing_clusters", [])):
        keep_tests.add(c["medoid_test"])
    ...
    edges.append({"from": e.src, "to": e.tgt, "type": e.type,
                  "structural_direction": e.structural_direction,
                  "influence_direction": e.influence_direction,
                  "path_count": len(e.path_ids),
                  "sample_path_ids": list(e.path_ids)[:5],
                  "omitted_path_ids_count": max(0, len(e.path_ids) - 5),
                  "test_status": e.test_status})
```
and put `clusters` + `selection_method` into the slice dict; keep `source_graph_stats`/`omission_note`/`dropped_counts`.

3. `persist`: also write `clusters.json` (the subgraph's `clusters` + `forced_paths` + `selection_method`).

- [ ] **Step 4: Run** `python3 -m pytest tests/test_rcc_graph_layers.py -q` → all pass (adapt any prior test that asserted the old `unknown_reachable_sample` key → now `unknown_reachable_clusters`).

- [ ] **Step 5: Commit**
```bash
git add abench/rcc_graph_layers.py tests/test_rcc_graph_layers.py
git commit -m "feat(rcc): subgraph/slice/persist use path clusters — cluster frontier + sampled edge path_ids + clusters.json (R3-lite)"
```

---

### Task 3: Alpha/Gamma render clusters; fixtures; regen inspector

**Files:** Modify `abench/rcc_prompts.py`, `tests/test_rcc_prompts.py`; adapt `tests/test_rcc_graph.py`/`tests/test_rcc_orchestrate.py` fixtures if they built a slice with the old frontier keys.

- [ ] **Step 1:** Update `_frontier_block` in `abench/rcc_prompts.py` to render clusters:

```python
def _frontier_block(sl: dict) -> str:
    f = sl.get("test_frontier", {})
    lines = [f"FAILED ({len(f.get('failed', []))}): " + ", ".join(f.get("failed", []))]
    cl = f.get("unknown_reachable_clusters", [])
    if cl:
        lines.append("reachable-path CLUSTERS (representative usage scenarios, medoid "
                     "per cluster):")
        for c in cl:
            lines.append(f"  - [{c['size']} paths] {c['path_shape']}  "
                         f"(e.g. {c['medoid_test']})")
    if f.get("passing_clusters"):
        lines.append(f"passing clusters: {len(f['passing_clusters'])}")
    return "\n".join(lines)
```

(alpha_prompt/gamma_prompt already call `_frontier_block(sl)` — no other change. The stats line + omission note are unchanged.)

- [ ] **Step 2:** Update `tests/test_rcc_prompts.py`: the `_SLICE` fixture's `test_frontier` uses `unknown_reachable_clusters` (a list of `{size, path_shape, medoid_test}`) instead of `unknown_reachable_sample`; assert Alpha/Gamma contain `path_shape` text and "CLUSTERS". Fix any test that referenced the old sample key.

- [ ] **Step 3:** `tests/test_rcc_graph.py` / `tests/test_rcc_orchestrate.py`: if their `_SLICE`/`_build_slice` fixtures are built via the real layer fns, they update automatically; if hand-built, switch `unknown_reachable_sample` → `unknown_reachable_clusters`. Run `python3 -m pytest tests/ -q -k "rcc or orchestr"` → all pass.

- [ ] **Step 4:** `python3 -c "import abench.runner"` → ok. Then a real-slice sanity check:
```bash
python3 -c "
from abench.rcc_mgraph_build import artifact_builder
from abench.rcc_graph_layers import annotate_status, build_index, build_subgraph, render_slice
g=artifact_builder('/wd','putValue',{},artifact_path='experiments/picocli-putValue/gt-out/slice-work/357b6bd1af378e00.graph.json')
f={'picocli.HelpTest.testTextTablePutValue_NullOrEmpty'}
annotate_status(g,failed_ids=f); gs=build_subgraph(g,failed_ids=f)
cl=gs['test_frontier']['unknown_reachable_clusters']
print('clusters:',len(cl))
for c in cl: print(' ',c['size'],'|',c['path_shape'],'| e.g.',c['medoid_test'])
"
```
Expect several clusters with DIFFERENT `path_shape`s (direct addRowValues vs deeper synopsis/join chains).

- [ ] **Step 5:** Regenerate the inspector: update `/private/tmp/.../scratchpad/gen_rcc_stages.py` so the PromptSlice card + Alpha/Gamma reflect the clusters (frontier shows cluster shapes; edges show sampled path_ids). Run it to rewrite `scratchpad/rcc_stages.html`; report the new Alpha/Gamma token sizes. (The controller publishes the Artifact.)

- [ ] **Step 6: Commit**
```bash
git add abench/rcc_prompts.py tests/test_rcc_prompts.py tests/test_rcc_graph.py tests/test_rcc_orchestrate.py
git commit -m "feat(rcc): Alpha/Gamma render representative path clusters in the frontier (R3-lite)"
```

---

## Self-review
- **Spec coverage:** chains-as-points + weighted-LCS (Task 1); greedy k-medoids dependency-free (Task 1); status buckets, failed force-include (Task 1 cluster_chains + Task 2 build_subgraph); k formula (Task 1 `_k_for`); clusters.json (Task 2 persist); slice renders clusters + edge path sampling (Task 2 render_slice); Alpha/Gamma cluster summaries (Task 3); score demoted (kept, not used for diversity). All R3-lite points mapped.
- **Placeholder scan:** none; silhouette/PAM/HGT/passing-status/edge_type refinements are explicit Phase-3 seams.
- **Type consistency:** `cluster_chains(graph, *, k_unknown)` → dict with `clusters`/`forced_paths`/`selection_method`; `build_subgraph` frontier key `unknown_reachable_clusters` (list of cluster dicts) replaces `unknown_reachable_sample`; edges carry `path_count`/`sample_path_ids`/`omitted_path_ids_count` (no `path_ids`); `_frontier_block` reads the cluster list.

## Out of scope
Silhouette k-search / true PAM; `passing` status (JUnit-XML); edge-type distance tuning; the real GT-precompute artifact (spawned task); e2e-smoke.
