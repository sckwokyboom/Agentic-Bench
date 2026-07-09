# RapidCausalCoder R2 — layered graph (storage ≠ rendering) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop amputating the mutation graph. Keep the full substrate (GraphRaw), annotate/rank it with the failing tests, and render a compact, honestly-labeled PromptSlice into Alpha/Gamma — with GraphIndex stats + dropped_counts + a three-valued test status + typed directional edges + per-path selection_reason. Persist all four layers for inspection.

**Architecture:** GraphRaw (`MutationGraph`, full) → annotate_status(failed) → GraphIndex (stats) → GraphSubgraph/G_MS (ranked selection) → PromptSlice (bounded rendering). Alpha/Gamma consume the PromptSlice; CausalRank runs over GraphSubgraph. `focus()` (the R1 amputation) is retired from the driver. Failing tests PRIORITIZE, they do not DEFINE the graph.

**Tech Stack:** Python 3.11+, LangGraph (existing), pytest. No new deps.

Spec: `docs/superpowers/specs/2026-07-08-rapidcausalcoder-mvp-design.md` — **Revision R2** (+ R1).

---

## GT graph.json contract (verified)
`experiments/picocli-putValue/gt-out/slice-work/357b6bd1af378e00.graph.json`:
`target{fqn,signature,file,line_start,line_end,current_body}`; `method_bodies{fqn:{fqn,signature,file,line_start,line_end,sliced_body,...}}`; `chains[{id,depth,test:{fqn,file,line,sliced_body},steps:[{caller_ref,callee_ref,call_site:{file,line,code},args:[{index,origin,value|expr}],virtual}]}]` (refs "test"|"target"|<fqn>, test→…→target); `stats:{total_chains,distinct_tests,distinct_method_bodies,truncated}`.

## File Structure
- Modify: `abench/rcc_mutation_graph.py` — `MgChain`; `MutationGraph.chains/stats/change_origin`; `MgEdge.structural_direction/influence_direction/path_ids/test_status/source`; `MgVertex.status`.
- Modify: `abench/rcc_gt_parse.py` — preserve chains + stats + edge directions/path_ids + change_origin.
- Create: `abench/rcc_graph_layers.py` — annotate_status, build_index, score_chains, build_subgraph, render_slice, persist.
- Modify: `abench/rcc_prompts.py` — alpha_prompt/gamma_prompt render the PromptSlice.
- Modify: `abench/rcc_graph.py` — nodes consume the slice (prompts) + subgraph (rank).
- Modify: `abench/rcc_orchestrate.py` — build layers from `cur.failures`, persist, hand slice+subgraph to run_rcc.
- Tests: extend `tests/test_rcc_mutation_graph.py`, `tests/test_rcc_gt_parse.py`, `tests/test_rcc_prompts.py`, `tests/test_rcc_graph.py`, `tests/test_rcc_orchestrate.py`; create `tests/test_rcc_graph_layers.py`.

DO NOT touch unrelated uncommitted worktree changes. Known pre-existing unrelated failure: `tests/test_robustness.py::test_workdir_cleaned_up_when_client_raises`. The full suite OOMs on this machine — run `-k` subsets.

---

### Task 1: data-model extensions (MgChain, directions, status, stats, change_origin)

**Files:** Modify `abench/rcc_mutation_graph.py`; Test `tests/test_rcc_mutation_graph.py` (append).

- [ ] **Step 1: Append failing tests** to `tests/test_rcc_mutation_graph.py`:

```python
def test_edge_directions_and_status_default_and_set():
    from abench.rcc_mutation_graph import MgEdge
    e = MgEdge(src="test:T.a", tgt="method:C.m", type="TEST_ASSERTS")
    assert e.structural_direction is None and e.source == "gt"
    e2 = MgEdge(src="test:T.a", tgt="method:C.m", type="CALLS",
                structural_direction="test_to_method",
                influence_direction="method_to_test", path_ids=["p1"],
                test_status="failed")
    assert e2.influence_direction == "method_to_test" and e2.path_ids == ["p1"]


def test_chain_and_graph_stats_and_change_origin():
    from abench.rcc_mutation_graph import MgChain, MgEdge, MgVertex, MutationGraph
    ch = MgChain(id="p1", test_fqn="T.a", node_ids=["test:T.a", "method:C.m"],
                 status="failed")
    g = MutationGraph(
        target_id="method:C.m",
        vertices=[MgVertex(id="method:C.m", type="method", fqn="C.m", is_changed=True),
                  MgVertex(id="test:T.a", type="test", fqn="T.a", status="failed")],
        edges=[MgEdge(src="test:T.a", tgt="method:C.m", type="TEST_ASSERTS")],
        chains=[ch], stats={"chain_count": 1, "distinct_tests": 1},
        change_origin={"kind": "method_level_only", "method_fqn": "C.m",
                       "changed_statement_available": False})
    assert g.chains[0].status == "failed"
    assert g.stats["chain_count"] == 1
    assert g.change_origin["kind"] == "method_level_only"
    assert g.vertex("test:T.a").status == "failed"
```

- [ ] **Step 2: Run** `python3 -m pytest tests/test_rcc_mutation_graph.py -q` → the 2 new FAIL.

- [ ] **Step 3: Implement** — in `abench/rcc_mutation_graph.py`:

Add to `MgVertex` (after `source`):
```python
    status: "str | None" = None      # tests: "failed" | "passing" | "unknown_reachable"
```
Add to `MgEdge` (after `data_var`):
```python
    # R2: structural is the call/assert direction; influence is causal-propagation
    # direction (a method's behaviour influences the tests that assert it). path_ids
    # link an edge to the call chains it belongs to. test_status mirrors the chain's
    # test. source = provenance ("gt" | "llm").
    structural_direction: "str | None" = None
    influence_direction: "str | None" = None
    path_ids: list = field(default_factory=list)
    test_status: "str | None" = None
    source: str = "gt"
```
Add a new dataclass (after `MgEdge`):
```python
@dataclass
class MgChain:
    """A call chain (path) test → … → target from the GT graph. `node_ids` are
    vertex ids ordered test-first; `status` mirrors the chain's test."""
    id: str
    test_fqn: str
    node_ids: list = field(default_factory=list)
    status: "str | None" = None
```
Add to `MutationGraph` (after `classes_total`):
```python
    chains: list = field(default_factory=list)          # [MgChain]
    stats: dict = field(default_factory=dict)           # GraphRaw summary counts
    change_origin: dict = field(default_factory=dict)   # {kind, method_fqn, changed_statement_available}
```
(No behaviour change to existing methods; `focus()` stays but is no longer called by the driver — leave it.)

- [ ] **Step 4: Run** `python3 -m pytest tests/test_rcc_mutation_graph.py -q` → all pass (7 prior + 2 new).

- [ ] **Step 5: Commit**
```bash
git add abench/rcc_mutation_graph.py tests/test_rcc_mutation_graph.py
git commit -m "feat(rcc): R2 data model — MgChain, edge directions/path_ids/status, graph stats/change_origin"
```

---

### Task 2: parse_gt_graph preserves chains + stats + directions

**Files:** Modify `abench/rcc_gt_parse.py`; Test `tests/test_rcc_gt_parse.py` (append).

- [ ] **Step 1: Append tests**:

```python
def test_parse_preserves_chains_stats_and_directions():
    g = parse_gt_graph(_mini())
    # one chain per GT chain, ordered test-first, with a path id
    assert len(g.chains) == 1
    ch = g.chains[0]
    assert ch.test_fqn == "p.CT.t1"
    assert ch.node_ids[0] == "test:p.CT.t1" and ch.node_ids[-1] == "method:p.C.put"
    # edges carry directions + the chain's path id
    calls = [e for e in g.edges if e.type == "CALLS"]
    assert all(e.structural_direction and e.influence_direction for e in calls)
    assert any("p.CT.t1" in (e.path_ids and e.path_ids[0] or "") or e.path_ids
               for e in calls)
    # a TEST_ASSERTS edge is test→method structurally but method→test in influence
    ta = next(e for e in g.edges if e.type == "TEST_ASSERTS")
    assert ta.structural_direction == "test_to_method"
    assert ta.influence_direction == "method_to_test"
    assert g.change_origin["kind"] == "method_level_only"


def test_parse_carries_gt_stats_on_real_sample():
    import json as _json
    from pathlib import Path
    p = Path("experiments/picocli-putValue/gt-out/slice-work/357b6bd1af378e00.graph.json")
    if not p.is_file():
        import pytest
        pytest.skip("gt-out sample not present")
    g = parse_gt_graph(_json.loads(p.read_text()))
    assert g.stats.get("chain_count", 0) > 1000
    assert len(g.chains) > 1000
    assert g.stats.get("distinct_tests", 0) > 1000
```

- [ ] **Step 2: Run** `python3 -m pytest tests/test_rcc_gt_parse.py -q` → the 2 new FAIL.

- [ ] **Step 3: Implement** — in `abench/rcc_gt_parse.py`. Extend the parser:

1. When resolving a chain, build an `MgChain` and give each of its edges a `path_id`. Replace the chains loop body so it also collects chains + tags edges. Concretely, import `MgChain`, and inside `parse_gt_graph`:

```python
    chains: list = []
    edge_by_key: dict = {}                       # (src,tgt,type) -> MgEdge (to append path_ids)

    def add_edge(src, tgt_id, etype, path_id=None, test_status=None, **kw):
        if src == tgt_id:
            return
        key = (src, tgt_id, etype)
        e = edge_by_key.get(key)
        if e is None:
            struct = ("test_to_method" if etype == "TEST_ASSERTS"
                      else "caller_to_callee")
            infl = ("method_to_test" if etype == "TEST_ASSERTS"
                    else "callee_to_caller")
            e = MgEdge(src=src, tgt=tgt_id, type=etype,
                       structural_direction=struct, influence_direction=infl,
                       test_status=test_status, source="gt", **kw)
            edge_by_key[key] = e
            edges.append(e)
        if path_id and path_id not in e.path_ids:
            e.path_ids.append(path_id)
        if test_status and not e.test_status:
            e.test_status = test_status
```

Then in the chain loop, for each chain `ch`:
```python
        t_fqn = t.get("fqn")
        ...
        pid = ch.get("id") or f"chain_{len(chains)}"
        node_seq = [_test_id(t_fqn)]
        for st in ch.get("steps") or []:
            src = resolve(st.get("caller_ref", ""), t_fqn)
            dst = resolve(st.get("callee_ref", ""), t_fqn)
            add_edge(src, dst, "CALLS", path_id=pid, call_site=st.get("call_site"))
            for a in st.get("args") or []:
                if a.get("origin") in ("param", "method_call"):
                    add_edge(src, dst, "DATA_DEP", path_id=pid,
                             data_var=str(a.get("value") or a.get("expr") or a.get("index")))
            if node_seq[-1] != src:
                node_seq.append(src)
            node_seq.append(dst)
        add_edge(_test_id(t_fqn), target_id, "TEST_ASSERTS", path_id=pid)
        chains.append(MgChain(id=pid, test_fqn=t_fqn, node_ids=node_seq))
```
(Remove the old inline `add_edge`/edge-dedup that lacked directions/path_ids — this replaces it. Keep `resolve` and the vertex-adding code.)

2. Carry stats + change_origin into the returned graph:
```python
    gt_stats = graph_json.get("stats") or {}
    stats = {"method_count": sum(1 for v in vertices if v.type == "method"),
             "test_count": sum(1 for v in vertices if v.type in ("test", "assert")),
             "edge_count": len(edges),
             "chain_count": gt_stats.get("total_chains", len(chains)),
             "distinct_tests": gt_stats.get("distinct_tests",
                                            len({c.test_fqn for c in chains}))}
    change_origin = {"kind": "method_level_only", "method_fqn": target_fqn,
                     "changed_statement_available": False}
    return MutationGraph(target_id=target_id, vertices=vertices, edges=edges,
                         chains=chains, stats=stats, change_origin=change_origin)
```

- [ ] **Step 4: Run** `python3 -m pytest tests/test_rcc_gt_parse.py -q` → all pass (real-sample test runs).

- [ ] **Step 5: Commit**
```bash
git add abench/rcc_gt_parse.py tests/test_rcc_gt_parse.py
git commit -m "feat(rcc): parse_gt_graph preserves chains + GT stats + typed edge directions (R2)"
```

---

### Task 3: `rcc_graph_layers.py` — annotate_status + build_index

**Files:** Create `abench/rcc_graph_layers.py`; Test `tests/test_rcc_graph_layers.py`.

- [ ] **Step 1: Write tests**:

```python
# tests/test_rcc_graph_layers.py
from abench.rcc_graph_layers import annotate_status, build_index
from abench.rcc_mutation_graph import MgChain, MgEdge, MgVertex, MutationGraph


def _g():
    vs = [MgVertex(id="method:C.put", type="method", fqn="C.put", is_changed=True),
          MgVertex(id="method:C.caller", type="method", fqn="C.caller"),
          MgVertex(id="test:T.a", type="test", fqn="T.a"),
          MgVertex(id="test:T.b", type="test", fqn="T.b"),
          MgVertex(id="test:U.c", type="test", fqn="U.c")]
    es = [MgEdge(src="method:C.caller", tgt="method:C.put", type="CALLS"),
          MgEdge(src="test:T.a", tgt="method:C.put", type="TEST_ASSERTS"),
          MgEdge(src="test:T.b", tgt="method:C.put", type="TEST_ASSERTS"),
          MgEdge(src="test:U.c", tgt="method:C.caller", type="TEST_ASSERTS")]
    ch = [MgChain(id="p1", test_fqn="T.a", node_ids=["test:T.a", "method:C.put"]),
          MgChain(id="p2", test_fqn="T.b", node_ids=["test:T.b", "method:C.put"]),
          MgChain(id="p3", test_fqn="U.c", node_ids=["test:U.c", "method:C.caller",
                                                     "method:C.put"])]
    return MutationGraph(target_id="method:C.put", vertices=vs, edges=es, chains=ch,
                         stats={"chain_count": 3, "distinct_tests": 3})


def test_annotate_status_marks_failed_else_unknown_reachable():
    g = annotate_status(_g(), failed_ids={"T.a"})
    assert g.vertex("test:T.a").status == "failed"
    assert g.vertex("test:T.b").status == "unknown_reachable"
    assert g.vertex("test:U.c").status == "unknown_reachable"
    # chains mirror their test's status
    assert next(c for c in g.chains if c.id == "p1").status == "failed"
    assert next(c for c in g.chains if c.id == "p2").status == "unknown_reachable"


def test_annotate_status_with_passing_ids():
    g = annotate_status(_g(), failed_ids={"T.a"}, passing_ids={"T.b"})
    assert g.vertex("test:T.b").status == "passing"
    assert g.vertex("test:U.c").status == "unknown_reachable"


def test_build_index_summary():
    g = annotate_status(_g(), failed_ids={"T.a"})
    idx = build_index(g)
    assert idx["method_count"] == 2 and idx["test_count"] == 3
    assert idx["chain_count"] == 3
    assert idx["status_counts"] == {"failed": 1, "passing": 0, "unknown_reachable": 2}
    # top callers ranked by chains through them; addRowValues-style caller present
    assert idx["top_callers"][0]["method"] == "C.caller"
    assert idx["edge_type_counts"]["TEST_ASSERTS"] == 3
    assert set(idx["reachable_test_classes"]) == {"T", "U"}
```

- [ ] **Step 2: Run** → FAIL (module missing).

- [ ] **Step 3: Implement `abench/rcc_graph_layers.py`** (this task: annotate_status + build_index; score/subgraph/slice/persist in Tasks 4–5):

```python
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
```

- [ ] **Step 4: Run** `python3 -m pytest tests/test_rcc_graph_layers.py -q` → 3 pass.

- [ ] **Step 5: Commit**
```bash
git add abench/rcc_graph_layers.py tests/test_rcc_graph_layers.py
git commit -m "feat(rcc): R2 layers — annotate_status (3-valued) + build_index (GraphIndex)"
```

---

### Task 4: score_chains + build_subgraph (GraphSubgraph / G_MS)

**Files:** Modify `abench/rcc_graph_layers.py`; Test `tests/test_rcc_graph_layers.py` (append).

- [ ] **Step 1: Append tests**:

```python
def test_score_chains_prioritizes_failed_and_short():
    from abench.rcc_graph_layers import score_chains
    g = annotate_status(_g(), failed_ids={"T.a"})
    scored = score_chains(g)
    by_id = {s["path_id"]: s for s in scored}
    # failed path scores higher than an unknown one of equal length
    assert by_id["p1"]["score"] > by_id["p2"]["score"]
    assert "leads_to_failed_test" in by_id["p1"]["selection_reason"]
    # shorter path (p1 len2) beats a longer unknown path (p3 len3)
    assert by_id["p1"]["score"] > by_id["p3"]["score"]


def test_build_subgraph_keeps_all_failed_and_reports_drops():
    from abench.rcc_graph_layers import build_subgraph
    g = annotate_status(_g(), failed_ids={"T.a"})
    gs = build_subgraph(g, k_failed=10, k_passing=2, k_unknown=1)
    assert gs["target"] == "C.put"
    assert set(gs["methods"]) >= {"C.put", "C.caller"}   # target + direct caller
    assert gs["test_frontier"]["failed"] == ["T.a"]      # ALL failed ids
    # dropped counts reported (we asked for 1 unknown of 2)
    assert gs["dropped_counts"]["unknown_reachable"] >= 1
    # every selected path carries a reason
    assert all(p["selection_reason"] for p in gs["paths"])
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** — append to `abench/rcc_graph_layers.py`:

```python
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
```

- [ ] **Step 4: Run** `python3 -m pytest tests/test_rcc_graph_layers.py -q` → 5 pass.

- [ ] **Step 5: Commit**
```bash
git add abench/rcc_graph_layers.py tests/test_rcc_graph_layers.py
git commit -m "feat(rcc): R2 layers — score_chains + build_subgraph (ranked G_MS, dropped_counts, selection_reason)"
```

---

### Task 5: render_slice (PromptSlice) + persist

**Files:** Modify `abench/rcc_graph_layers.py`; Test `tests/test_rcc_graph_layers.py` (append).

- [ ] **Step 1: Append tests**:

```python
def test_render_slice_has_stats_frontier_and_omission():
    from abench.rcc_graph_layers import build_index, build_subgraph, render_slice
    g = annotate_status(_g(), failed_ids={"T.a"})
    slice_ = render_slice(g, build_subgraph(g), build_index(g))
    assert slice_["source_graph_stats"]["chain_count"] == 3
    assert slice_["test_frontier"]["failed"] == ["T.a"]
    assert slice_["omission_note"]                       # non-empty honesty note
    assert slice_["change_origin"]["kind"] == "method_level_only"
    # edges are typed objects with both directions, never strings
    e = slice_["edges"][0]
    assert set(e) >= {"from", "to", "type", "structural_direction", "influence_direction"}


def test_persist_writes_four_layers(tmp_path):
    from abench.rcc_graph_layers import build_index, build_subgraph, persist, render_slice
    g = annotate_status(_g(), failed_ids={"T.a"})
    idx, gs = build_index(g), build_subgraph(g)
    sl = render_slice(g, gs, idx)
    persist(tmp_path, g, idx, gs, sl)
    import json as _j
    for name in ("raw", "index", "subgraph", "slice"):
        assert (tmp_path / f"{name}.json").is_file()
    raw = _j.loads((tmp_path / "raw.json").read_text())
    assert raw["stats"]["chain_count"] == 3 and "SECRET" not in _j.dumps(raw)
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** — append to `abench/rcc_graph_layers.py`:

```python
def render_slice(graph: MutationGraph, subgraph: dict, index: dict) -> dict:
    """PromptSlice — the compact object Alpha/Gamma render. Carries the FULL-graph
    stats + dropped_counts + the omission note so the model can't infer that only the
    shown tests matter. Edges are typed objects (from/to/type/directions/status)."""
    keep_methods = set(subgraph["methods"])
    keep_tests = set(subgraph["test_frontier"]["failed"]
                     + subgraph["test_frontier"]["passing_sample"]
                     + subgraph["test_frontier"]["unknown_reachable_sample"])
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
                          "path_ids": e.path_ids, "test_status": e.test_status})
    total_tests = index["test_count"]
    shown = len(keep_tests)
    note = (f"This is a RANKED SLICE of a larger mutation graph: {index['method_count']} "
            f"methods, {index['distinct_tests']} reachable tests, {index['chain_count']} "
            f"call chains. Showing {len(subgraph['methods'])} methods and {shown} of "
            f"{total_tests} tests (all {len(subgraph['test_frontier']['failed'])} failed "
            f"+ samples). Omitted tests/paths are NOT necessarily irrelevant — "
            f"dropped_counts records what was left out. Influence flows method→test "
            f"(a method's behaviour influences the tests that assert it), the reverse of "
            f"the structural call direction.")
    return {"target": graph.target_fqn, "change_origin": graph.change_origin,
            "source_graph_stats": {k: index[k] for k in
                ("method_count", "test_count", "distinct_tests", "chain_count",
                 "edge_count", "status_counts", "top_callers")},
            "methods": methods, "edges": edges,
            "test_frontier": subgraph["test_frontier"],
            "paths": subgraph["paths"], "dropped_counts": subgraph["dropped_counts"],
            "omission_note": note}


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


def persist(out_dir, graph, index, subgraph, slice_) -> None:
    """Write the four layers for inspection / the future trace-visualizer. Best-effort."""
    try:
        d = Path(out_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / "raw.json").write_text(json.dumps(_graph_to_dict(graph), indent=1))
        (d / "index.json").write_text(json.dumps(index, indent=1))
        (d / "subgraph.json").write_text(json.dumps(subgraph, indent=1))
        (d / "slice.json").write_text(json.dumps(slice_, indent=1))
    except OSError:
        pass
```

- [ ] **Step 4: Run** `python3 -m pytest tests/test_rcc_graph_layers.py -q` → 7 pass.

- [ ] **Step 5: Commit**
```bash
git add abench/rcc_graph_layers.py tests/test_rcc_graph_layers.py
git commit -m "feat(rcc): R2 layers — render_slice (PromptSlice: stats+frontier+omission) + persist 4 layers"
```

---

### Task 6: Alpha/Gamma render the PromptSlice

**Files:** Modify `abench/rcc_prompts.py`; Test `tests/test_rcc_prompts.py` (append + adapt).

- [ ] **Step 1: Append tests** (the slice is a dict; new signatures `alpha_prompt(slice_)` / `gamma_prompt(slice_, specs, logs)`):

```python
_SLICE = {
    "target": "p.C.put",
    "change_origin": {"kind": "method_level_only", "method_fqn": "p.C.put",
                      "changed_statement_available": False},
    "source_graph_stats": {"method_count": 90, "test_count": 1406, "distinct_tests": 1406,
        "chain_count": 1526, "edge_count": 3375,
        "status_counts": {"failed": 3, "passing": 0, "unknown_reachable": 1403},
        "top_callers": [{"method": "p.C.addRowValues", "chains": 1256}]},
    "methods": [{"fqn": "p.C.put", "role": "target", "signature": "Cell(int,int,Text)",
                 "source": None, "source_available_from_workdir": True},
                {"fqn": "p.C.addRowValues", "role": "caller_or_callee",
                 "signature": "void(Text[])", "source": "void addRowValues(){...}",
                 "source_available_from_workdir": False}],
    "edges": [{"from": "method:p.C.addRowValues", "to": "method:p.C.put", "type": "CALLS",
               "structural_direction": "caller_to_callee",
               "influence_direction": "callee_to_caller", "path_ids": ["p2"],
               "test_status": None}],
    "test_frontier": {"failed": ["p.HT.tPut"], "passing_sample": [],
                      "unknown_reachable_sample": ["p.HT.tOther"]},
    "paths": [{"path_id": "p1", "status": "failed", "score": 145,
               "selection_reason": ["leads_to_failed_test", "direct_caller_path"]}],
    "dropped_counts": {"unknown_reachable": 1400},
    "omission_note": "This is a RANKED SLICE ... method->test influence ...",
}


def test_alpha_over_slice_has_stats_and_omission():
    a = alpha_prompt(_SLICE)
    assert "p.C.put" in a and "addRowValues" in a
    assert "1526" in a and "RANKED SLICE" in a           # full-graph stats + honesty
    assert "CALLS" in a and "pre" in a and "edge" in a.lower()


def test_gamma_over_slice_has_frontier_and_influence():
    g = gamma_prompt(_SLICE, "SPECS", ["RCC_PROBE put: ret=null"])
    assert "ret=null" in g and "mutation_vertex" in g
    assert "influence" in g.lower()                      # method->test direction cue
    assert "p.HT.tPut" in g                              # failed frontier present
    assert "dropped" in g.lower() or "omitted" in g.lower()
```

Also UPDATE the existing `_g()`-based Alpha/Gamma tests in this file: they now build a slice via `render_slice`. Simplest: keep the old MutationGraph `_g()` and wrap — replace the old `alpha_prompt(_g())` calls with `alpha_prompt(render_slice(annotate_status(_g(), failed_ids=set()), build_subgraph(...), build_index(...)))`. (Import the layer fns.) Adjust the assertions that referenced the old vertices/edges block to the slice equivalents.

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** — in `abench/rcc_prompts.py`, change `alpha_prompt`/`beta_prompt`/`gamma_prompt` to take the PromptSlice dict. Replace `_vertices_block`/`_edges_block` (which took a MutationGraph) with slice-based renderers:

```python
def _stats_line(sl: dict) -> str:
    s = sl.get("source_graph_stats", {})
    tc = (s.get("top_callers") or [{}])[0]
    return (f"Full mutation graph: {s.get('method_count','?')} methods, "
            f"{s.get('distinct_tests','?')} reachable tests, {s.get('chain_count','?')} "
            f"call chains; status {s.get('status_counts', {})}; "
            f"top caller: {tc.get('method','?')} ({tc.get('chains','?')} chains).")


def _methods_block(sl: dict) -> str:
    parts = []
    for m in sl.get("methods", []):
        tag = " [CHANGED/TARGET]" if m.get("role") == "target" else ""
        src = m.get("source") or ("(target body — read it from the workdir)"
                                  if m.get("source_available_from_workdir")
                                  else "(source unavailable — read it yourself)")
        parts.append(f"### {m['fqn']}{tag}  {m.get('signature') or ''}\n```java\n{src}\n```")
    return "\n".join(parts)


def _edges_block(sl: dict) -> str:
    rows = []
    for e in sl.get("edges", []):
        extra = f"  (influence: {e.get('influence_direction')})"
        st = f" [{e['test_status']}]" if e.get("test_status") else ""
        rows.append(f"- {e['from']} --{e['type']}--> {e['to']}{st}{extra}")
    return "\n".join(rows) or "(no edges in slice)"


def _frontier_block(sl: dict) -> str:
    f = sl.get("test_frontier", {})
    return (f"FAILED ({len(f.get('failed', []))}): " + ", ".join(f.get("failed", [])) + "\n"
            f"passing sample: " + ", ".join(f.get("passing_sample", []) or ["(none)"]) + "\n"
            f"unknown-reachable sample: "
            + ", ".join(f.get("unknown_reachable_sample", []) or ["(none)"]))


def alpha_prompt(sl: dict) -> str:
    return (
        "You are writing CONTRACTS over a MUTATION GRAPH slice (call/dataflow structure "
        f"around the changed method {sl.get('target')}).\n" + _stats_line(sl) + "\n"
        + sl.get("omission_note", "") + "\n\n"
        "For EACH METHOD vertex: a vertex contract (pre/post/inv).\n"
        "For EACH CALLS/DATA_DEP EDGE: an interaction contract (what the caller expects "
        "of the callee; for DATA_DEP the constraint on the flowing variable).\n"
        "Do NOT edit code.\n\nMETHODS:\n" + _methods_block(sl)
        + "\n\nEDGES:\n" + _edges_block(sl)
        + "\n\nTEST FRONTIER:\n" + _frontier_block(sl))


def beta_prompt(sl: dict, specs_text: str) -> str:
    return (
        "Instrument the code for INVASIVE DEBUGGING to check the contracts against actual "
        "runtime values. Insert System.out.println lines into the methods below. EVERY "
        f"inserted line: start its message with \"{PROBE_PREFIX} <Class.method>: \" and "
        "print args at entry + return at exit + key branch state; end with the trailing "
        f"comment {PROBE_MARKER} on the SAME line; change NO behaviour; keep it compiling."
        "\n\nCONTRACTS:\n" + _cap(specs_text, _MAX_SPECS_CHARS)
        + "\n\nMETHODS:\n" + _methods_block(sl))


def beta_repair_prompt(sl: dict) -> str:
    return ("The instrumented build no longer compiles. Fix the compilation — delete a "
            f"probe line rather than leave it broken. Keep each probe's trailing "
            f"{PROBE_MARKER}. Do not change program logic.")


def gamma_prompt(sl: dict, specs_text: str, probe_lines: list) -> str:
    logs = "\n".join((probe_lines or [])[:_MAX_LOG_LINES]) \
        or "(no runtime logs — instrumentation was skipped)"
    mids = "\n".join(f"- method:{m['fqn']}" for m in sl.get("methods", []))
    return (
        "Build a CausalDeltaSubGraph. Compare each method/edge CONTRACT against the "
        "runtime PROBE LOGS; mark violations, the root cause, and the downstream cascade.\n"
        "IMPORTANT: influence flows method→test (a method's behaviour influences the "
        "tests that assert it) — the REVERSE of the structural call direction. Reason "
        "about causation in the influence direction.\n" + _stats_line(sl) + "\n"
        + sl.get("omission_note", "") + "\n"
        "Return ONLY JSON: " '{"vertices": [{"id","mutation_vertex","type":'
        '"root_cause|downstream_effect|spec_violation|unaffected","spec_text","spec_level":'
        '"L1|L2|L3","runtime_value","violated","is_root_cause","confidence"}], '
        '"edges": [{"from","to","type":"CAUSES|CONTRIBUTES_TO|DATA_FLOWS_INTO|'
        'CONTRACT_REFINES","path","reasoning"}]}.\n'
        "Exactly one vertex is_root_cause=true. mutation_vertex MUST be one of:\n"
        + mids + "\n\nTEST FRONTIER:\n" + _frontier_block(sl)
        + "\n\nCONTRACTS:\n" + _cap(specs_text, _MAX_SPECS_CHARS)
        + "\n\nPROBE LOGS:\n" + logs)
```

Keep `fix_prompt`, `cache_fix_prompt`, `parse_causal_delta`, `causal_rank`, `root_rank` unchanged (they take the causal graph + method list, not the slice). `causal_rank(graph, methods)` still takes a plain method-fqn list — the caller passes `[m['fqn'] for m in slice['methods']]` or the subgraph methods.

- [ ] **Step 4: Run** `python3 -m pytest tests/test_rcc_prompts.py -q` → all pass.

- [ ] **Step 5: Commit**
```bash
git add abench/rcc_prompts.py tests/test_rcc_prompts.py
git commit -m "feat(rcc): Alpha/Gamma render the PromptSlice — stats header, frontier, omission, influence direction (R2)"
```

---

### Task 7: wire the layers into the loop + driver; regenerate the inspector

**Files:** Modify `abench/rcc_graph.py`, `abench/rcc_orchestrate.py`; Tests `tests/test_rcc_graph.py`, `tests/test_rcc_orchestrate.py`.

- [ ] **Step 1: Rewire `run_rcc` (`abench/rcc_graph.py`)** to consume a PromptSlice + a method list, not the raw MutationGraph:
  - `run_rcc(cfg, slice_, methods, initial, *, ...)` — replace the `sub: MutationGraph` param with `slice_` (dict) + `methods` (list of fqns, target first). Update the nodes: `alpha_prompt(slice_)`, `beta_prompt(slice_, specs)`, `gamma_prompt(slice_, specs, probes)`; `causal_rank(graph, methods)`; `root_rank(ranks, methods[0])`; memory key = `methods[0]`; `sub.test_classes` (for subset run) → derive from `slice_["test_frontier"]` (the failed + sampled test classes) — add a small helper `_slice_test_classes(slice_)`. `sub.methods()` → `methods`. The "mutation graph:" event uses the slice stats.
  - Update `tests/test_rcc_graph.py` fixtures: `_SUB` → a `_SLICE` dict + `_METHODS` list; pass both to `run_rcc`. Keep the scenario assertions (green/defer/telemetry) intact.

- [ ] **Step 2: Rewire `run_rcc_condition` (`abench/rcc_orchestrate.py`)** — after the RED implement suite, build the layers and hand the slice + methods to run_rcc. Replace the R1 `focus(...)` block with:

```python
    from .rcc_graph_layers import (annotate_status, build_index, build_subgraph,
                                    persist, render_slice)
    failed = {f"{f.classname}.{f.name}" for f in cur.failures}
    annotate_status(sub, failed_ids=failed)
    index = build_index(sub)
    subgraph = build_subgraph(sub, failed_ids=failed,
                              k_methods=rcfg.subset_class_cap and 8 or 8)
    slice_ = render_slice(sub, subgraph, index)
    if persist_dir is not None:
        persist(persist_dir, sub, index, subgraph, slice_)
    methods = subgraph["methods"]
    event(f"graph layers: raw {index['method_count']}m/{index['distinct_tests']}t/"
          f"{index['chain_count']}chains → subgraph {len(methods)} methods, "
          f"frontier {len(subgraph['test_frontier']['failed'])} failed "
          f"+ {len(subgraph['test_frontier']['unknown_reachable_sample'])} sampled", "implement")
    ...
    return run_rcc(rcfg, slice_, methods, cur, ...)
```
Add a `persist_dir=None` kwarg to `run_rcc_condition`.

- [ ] **Step 3: Runner** (`abench/runner.py`) — pass `persist_dir=rundir / "rcc-graph"` into `run_rcc_condition`, and (unchanged) the full `mg` as `sub`.

- [ ] **Step 4: Run** `python3 -m pytest tests/ -q -k "rcc or orchestr"` → all pass; `python3 -c "import abench.runner"` → ok.

- [ ] **Step 5: Regenerate the inspector** — update `/private/tmp/.../scratchpad/gen_rcc_stages.py` to build the slice via the R2 layers (annotate_status → build_index → build_subgraph → render_slice) and render `alpha_prompt(slice_)` / `gamma_prompt(slice_, …)`; add a stage card for the GraphIndex stats + the PromptSlice JSON (showing stats header + frontier + dropped_counts). Re-publish the Artifact so the user can inspect the corrected pipeline.

- [ ] **Step 6: Commit**
```bash
git add abench/rcc_graph.py abench/rcc_orchestrate.py abench/runner.py tests/test_rcc_graph.py tests/test_rcc_orchestrate.py
git commit -m "feat(rcc): wire R2 layers into the loop+driver — slice to prompts, subgraph to rank, persist 4 layers"
```

---

## Self-review
- **Spec coverage:** GraphRaw preserved (Task 1–2, driver no longer amputates — Task 7); GraphIndex (Task 3); GraphSubgraph ranked + dropped_counts + selection_reason (Task 4); PromptSlice stats+frontier+omission+typed-directional edges (Task 5–6); 3-valued status, no false "passing" (Task 3, annotate_status only marks passing when explicitly supplied); persist 4 layers (Task 5, 7); change_origin now (Task 2); CausalRank over subgraph not raw (Task 7). All 8 R2 refinements mapped.
- **Placeholder scan:** none; `passing` status + k-medoid/HGT/coverage_hits/changed-statement are explicit Phase-3 seams (spec R2 deferred).
- **Type consistency:** `alpha_prompt`/`beta_prompt`/`gamma_prompt` all take the slice dict (Task 6); `run_rcc(cfg, slice_, methods, initial, …)` (Task 7); `causal_rank(graph, methods)` keeps its 2-arg method-list shape; layer fns are `annotate_status/build_index/score_chains/build_subgraph/render_slice/persist`.

## Out of scope
Real GT-precompute of the shipped artifact (spawned task); k-medoid/HGT ranking; JUnit-XML passing-id parse; changed-statement vertex; coverage_hits; the canvas graph overlay.
