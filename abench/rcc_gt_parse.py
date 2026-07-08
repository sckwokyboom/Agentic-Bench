"""Parse a Graph-Tipper graph.json into a leak-safe MutationGraph.

The parser STRUCTURALLY drops the target's ``current_body`` (the reference's
correct implementation = the tipper) — it can never emit it. At runtime the
GT builder runs on the AGENT's workdir and passes the agent's own target source
via ``target_source``; for the committed fixture (built on the reference) no
override is given, so the target vertex carries no body (leak-clean)."""
from __future__ import annotations

from .rcc_mutation_graph import MgEdge, MgVertex, MutationGraph

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
    edge_seen: set = set()

    def add_edge(src: str, tgt_id: str, etype: str, **kw) -> None:
        key = (src, tgt_id, etype)
        if src != tgt_id and key not in edge_seen:
            edge_seen.add(key)
            edges.append(MgEdge(src=src, tgt=tgt_id, type=etype, **kw))

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
        for st in ch.get("steps") or []:
            src = resolve(st.get("caller_ref", ""), t_fqn)
            dst = resolve(st.get("callee_ref", ""), t_fqn)
            cs = st.get("call_site")
            add_edge(src, dst, "CALLS", call_site=cs)
            for a in st.get("args") or []:
                if a.get("origin") in ("param", "method_call"):
                    add_edge(src, dst, "DATA_DEP",
                             data_var=str(a.get("value") or a.get("expr") or a.get("index")))
        add_edge(_test_id(t_fqn), target_id, "TEST_ASSERTS")

    return MutationGraph(target_id=target_id, vertices=vertices, edges=edges)
