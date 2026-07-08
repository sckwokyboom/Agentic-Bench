# tests/test_rcc_prompts.py
from abench.rcc_mutation_graph import MgEdge, MgVertex, MutationGraph
from abench.rcc_prompts import (GAMMA_FORMAT_REMINDER, PROBE_MARKER, PROBE_PREFIX,
                                alpha_prompt, beta_prompt, beta_repair_prompt)


def _g():
    vs = [MgVertex(id="method:p.C.put", type="method", fqn="p.C.put", is_changed=True,
                   l1_skeleton={"signature": "Cell(int,int,Text)"},
                   source="Cell put(int r,int c,Text v){ return null; }"),
          MgVertex(id="method:p.C.get", type="method", fqn="p.C.get",
                   source="Object get(){...}"),
          MgVertex(id="test:p.CT.t1", type="test", fqn="p.CT.t1", source="assertX()")]
    es = [MgEdge(src="method:p.C.put", tgt="method:p.C.get", type="CALLS",
                 call_site={"file": "C.java", "line": 31, "code": "get()"}),
          MgEdge(src="method:p.C.put", tgt="method:p.C.get", type="DATA_DEP",
                 data_var="value"),
          MgEdge(src="test:p.CT.t1", tgt="method:p.C.put", type="TEST_ASSERTS")]
    return MutationGraph(target_id="method:p.C.put", vertices=vs, edges=es)


def test_alpha_covers_vertices_and_edges():
    a = alpha_prompt(_g())
    assert "p.C.put" in a and "return null" in a           # vertex source shown
    assert "CALLS" in a and "get()" in a                    # edge with call_site
    assert "DATA_DEP" in a and "value" in a                 # dataflow edge
    assert "edge" in a.lower() and "pre" in a               # asks for edge + vertex specs


def test_beta_prompt_targets_graph_methods():
    b = beta_prompt(_g(), "SPECS")
    assert PROBE_PREFIX in b and PROBE_MARKER in b and "SPECS" in b
    assert "p.C.put" in b
    assert PROBE_MARKER in beta_repair_prompt(_g())
