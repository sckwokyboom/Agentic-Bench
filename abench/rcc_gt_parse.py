"""Parse a Graph-Tipper graph.json into a leak-safe MutationGraph.

The parser STRUCTURALLY drops the target's ``current_body`` (the reference's
correct implementation = the tipper) — it can never emit it. At runtime the
GT builder runs on the AGENT's workdir and passes the agent's own target source
via ``target_source``; for the committed fixture (built on the reference) no
override is given, so the target vertex carries no body (leak-clean)."""
from __future__ import annotations

from .rcc_mutation_graph import MgChain, MgEdge, MgVertex, MutationGraph

_TARGET_ID = "target"


def _method_id(fqn: str) -> str:
    return f"method:{fqn}"


def _test_id(fqn: str) -> str:
    return f"test:{fqn}"


def _skeleton(signature: "str | None") -> "dict | None":
    return {"signature": signature} if signature else None


def parse_gt_graph(graph_json: dict, *, target_source: "str | None" = None) -> MutationGraph:
    tgt = graph_json.get("target") or {}
    target_fqn = tgt.get("fqn", "")
    target_id = _method_id(target_fqn)

    vertices: list = []
    seen: set = set()

    def add(v: MgVertex) -> None:
        if v.id not in seen:
            seen.add(v.id)
            vertices.append(v)

    add(MgVertex(id=target_id, type="method", fqn=target_fqn, is_changed=True,
                 location={"file": tgt.get("file"), "line_start": tgt.get("line_start"),
                           "line_end": tgt.get("line_end")},
                 l1_skeleton=_skeleton(tgt.get("signature")), source=target_source))

    for fqn, mb in (graph_json.get("method_bodies") or {}).items():
        add(MgVertex(id=_method_id(fqn), type="method", fqn=fqn,
                     location={"file": mb.get("file"), "line_start": mb.get("line_start"),
                               "line_end": mb.get("line_end")},
                     l1_skeleton=_skeleton(mb.get("signature")),
                     source=mb.get("sliced_body")))

    edges: list = []
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

    def resolve(ref: str, test_fqn: str) -> str:
        if ref == "test":
            return _test_id(test_fqn)
        if ref == _TARGET_ID:
            return target_id
        return _method_id(ref)

    for ch in graph_json.get("chains") or []:
        t = ch.get("test") or {}
        t_fqn = t.get("fqn")
        if not t_fqn:
            continue
        add(MgVertex(id=_test_id(t_fqn), type="test", fqn=t_fqn,
                     location={"file": t.get("file"), "line_start": t.get("line"),
                               "line_end": t.get("line")},
                     source=t.get("sliced_body")))
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
