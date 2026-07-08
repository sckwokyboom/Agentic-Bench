# RapidCausalCoder R1 — real MutationGraph + CausalDeltaSubGraph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace RCC's flat coverage-overlap "subgraph" with a real typed `MutationGraph` (call/dataflow structure), built by a pluggable `build_mutation_graph` seam (GT-kgpool on the workdir, primary; LLM, fallback); lift Alpha to vertex+edge contracts and Gamma to a full `CausalDeltaSubGraph`; rank by root-cause×confidence. All consumption is built and tested on this Mac against a fixture carved from the committed `gt-out` graph.json — the real GT builder is a subprocess adapter validated on the prepared box.

**Architecture:** Placement per R1: the RCC *orchestration harness* stays in Agentic-Bench (it produces a `Trace`, drives `phase_runner`/`suite_runner`, must stay measurable + testable in-repo); the *graph analysis* lives in Graph-Tipper, consumed via the subprocess seam. The graph is ALWAYS built from the agent's workdir (leak-safe); `gt-out` is a body-stripped test fixture only. Node signatures in `rcc_graph.py` are preserved so Phase-2 wiring is unaffected.

**Tech Stack:** Python 3.11+, LangGraph (existing extra), pytest. No new runtime deps.

Spec: `docs/superpowers/specs/2026-07-08-rapidcausalcoder-mvp-design.md` — **Revision R1** (sections R1.1–R1.7).

---

## GT graph.json contract (verified against the committed sample)

`experiments/picocli-putValue/gt-out/slice-work/357b6bd1af378e00.graph.json`:
- `target`: `{fqn, signature, file, line_start, line_end, current_body}` — `current_body` is the CORRECT impl (leak) → **dropped by the parser**.
- `method_bodies`: `{fqn: {fqn, signature, file, line_start, line_end, sliced_body, sliced_body_truncated, warnings}}` — neighbor methods (unchanged library code; `sliced_body` is legit source). Target is NOT in here.
- `chains`: `[{id, depth, virtual_steps, test: {fqn, file, line, sliced_body}, steps: [{caller_ref, callee_ref, call_site: {file,line,column,code}, args: [{index, origin, value|expr}], virtual}]}]`. Refs ∈ `"test" | "target" | <method fqn>`; chains run test → intermediates → target.

## File Structure

- Create: `abench/rcc_mutation_graph.py` — `MgVertex`/`MgEdge`/`MutationGraph` + derivations.
- Create: `abench/rcc_gt_parse.py` — `parse_gt_graph(graph_json, *, target_source=None) -> MutationGraph`.
- Create: `abench/rcc_mgraph_build.py` — `build_mutation_graph` seam + `llm_builder` + `gt_kgpool_builder` + `parse_mgraph_json`.
- Rewrite: `abench/rcc_prompts.py` — Alpha (vertex+edge contracts), Gamma (CausalDeltaSubGraph), `parse_causal_delta`, `causal_rank` (root-cause×confidence), `root_rank`; keep `beta_prompt`/`beta_repair_prompt`/`fix_prompt`/`cache_fix_prompt` adapted to `MutationGraph`; keep `PROBE_MARKER`/`PROBE_PREFIX`/`GAMMA_FORMAT_REMINDER`.
- Modify: `abench/rcc_graph.py` — swap `RccSubgraph`→`MutationGraph`, add a build node, gamma parses `CausalDeltaSubGraph`, rank uses the new `causal_rank`.
- Delete: `abench/rcc_subgraph.py` + `tests/test_rcc_subgraph.py` (superseded — the coverage-overlap builder and its `shared_test_edges` stopgap are gone).
- Tests: `tests/test_rcc_mutation_graph.py`, `tests/test_rcc_gt_parse.py`, `tests/test_rcc_mgraph_build.py`, rewritten `tests/test_rcc_prompts.py`, updated `tests/test_rcc_graph.py`.

DO NOT touch the unrelated uncommitted worktree changes (web/, abench_ui/static, experiments WIP yaml/dirs). Known pre-existing unrelated failure on main: `tests/test_robustness.py::test_workdir_cleaned_up_when_client_raises`.

---

### Task 1: `MutationGraph` data model

**Files:**
- Create: `abench/rcc_mutation_graph.py`
- Test: `tests/test_rcc_mutation_graph.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_rcc_mutation_graph.py
from abench.rcc_mutation_graph import MgEdge, MgVertex, MutationGraph


def _g():
    vs = [
        MgVertex(id="method:p.C.put", type="method", fqn="p.C.put", is_changed=True),
        MgVertex(id="method:p.C.get", type="method", fqn="p.C.get"),
        MgVertex(id="test:p.CT.t1", type="test", fqn="p.CT.t1"),
        MgVertex(id="test:p.DT.t2", type="test", fqn="p.DT.t2"),
    ]
    es = [
        MgEdge(src="test:p.CT.t1", tgt="method:p.C.put", type="CALLS"),
        MgEdge(src="method:p.C.put", tgt="method:p.C.get", type="CALLS"),
        MgEdge(src="test:p.CT.t1", tgt="method:p.C.put", type="TEST_ASSERTS"),
        MgEdge(src="test:p.DT.t2", tgt="method:p.C.put", type="TEST_ASSERTS"),
    ]
    return MutationGraph(target_id="method:p.C.put", vertices=vs, edges=es)


def test_methods_lists_method_vertices_target_first():
    g = _g()
    assert g.methods() == ["p.C.put", "p.C.get"]     # target first, then others
    assert g.target_fqn == "p.C.put"


def test_test_classes_and_fqns_derived_from_test_vertices():
    g = _g()
    assert g.test_fqns == ["p.CT.t1", "p.DT.t2"]
    assert g.test_classes == ["p.CT", "p.DT"]
    assert g.classes_total == 2


def test_vertex_lookup_and_edges_of():
    g = _g()
    assert g.vertex("method:p.C.get").fqn == "p.C.get"
    assert g.vertex("nope") is None
    calls_from_put = [e for e in g.edges_from("method:p.C.put") if e.type == "CALLS"]
    assert [e.tgt for e in calls_from_put] == ["method:p.C.get"]


def test_class_cap_keeps_classes_by_test_count():
    g = _g()
    capped = g.with_class_cap(1)   # p.CT and p.DT each have 1 test -> name order
    assert capped.test_classes == ["p.CT"]
    assert capped.classes_total == 2            # pre-cap count preserved
    assert capped.test_fqns == ["p.CT.t1"]
```

- [ ] **Step 2: Run** `python3 -m pytest tests/test_rcc_mutation_graph.py -q` — FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `abench/rcc_mutation_graph.py`**

```python
"""RapidCausalCoder R1 — the typed mutation graph (call/dataflow structure).

Vertices are methods / tests / asserts; edges are CALLS / DATA_DEP / CONTROL_DEP /
TEST_ASSERTS / OVERRIDES. This is the structural backbone Alpha/Gamma reason over
(replaces the old coverage-overlap flat list). Always built from the AGENT's
workdir (see rcc_mgraph_build) — never ground truth. Pure data + derivations."""
from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass
class MgVertex:
    id: str                                  # "method:fqn" | "test:fqn" | "assert:..."
    type: str                                # "method" | "test" | "assert"
    fqn: str
    location: "dict | None" = None           # {file, line_start, line_end}
    is_changed: bool = False                 # directly modified by the diff
    l1_skeleton: "dict | None" = None        # {signature, params, return_type, local_vars}
    source: "str | None" = None              # body FROM THE WORKDIR (leak-safe)


@dataclass
class MgEdge:
    src: str
    tgt: str
    type: str                                # CALLS|DATA_DEP|CONTROL_DEP|TEST_ASSERTS|OVERRIDES
    call_site: "dict | None" = None          # {file, line, code} for CALLS
    data_var: "str | None" = None            # for DATA_DEP


@dataclass
class MutationGraph:
    target_id: str
    vertices: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    classes_total: int = 0                   # distinct test classes BEFORE any class cap

    def __post_init__(self):
        self._by_id = {v.id: v for v in self.vertices}
        if not self.classes_total:
            self.classes_total = len(self.test_classes)

    def vertex(self, vid: str) -> "MgVertex | None":
        return self._by_id.get(vid)

    def edges_from(self, vid: str) -> list:
        return [e for e in self.edges if e.src == vid]

    @property
    def target_fqn(self) -> str:
        v = self.vertex(self.target_id)
        return v.fqn if v else ""

    def methods(self) -> list:
        """Method-vertex FQNs, target first, then the rest in vertex order."""
        ms = [v.fqn for v in self.vertices if v.type == "method"]
        tf = self.target_fqn
        return ([tf] + [m for m in ms if m != tf]) if tf in ms else ms

    @property
    def _test_vertices(self) -> list:
        return [v for v in self.vertices if v.type in ("test", "assert")]

    @property
    def test_fqns(self) -> list:
        return sorted({v.fqn for v in self._test_vertices})

    @property
    def test_classes(self) -> list:
        return sorted({v.fqn.rsplit(".", 1)[0] for v in self._test_vertices})

    def with_class_cap(self, cap: "int | None") -> "MutationGraph":
        """A copy keeping only the top-`cap` test classes (ranked by number of test
        vertices, then name) — the subset-cost control for dense targets. Method
        vertices + their edges are untouched; classes_total keeps the pre-cap count."""
        if not cap or cap <= 0:
            return self
        by_class: dict = {}
        for v in self._test_vertices:
            by_class.setdefault(v.fqn.rsplit(".", 1)[0], []).append(v)
        ranked = sorted(by_class, key=lambda c: (-len(by_class[c]), c))[:cap]
        keep = set(ranked)
        drop_ids = {v.id for v in self._test_vertices
                    if v.fqn.rsplit(".", 1)[0] not in keep}
        vs = [v for v in self.vertices if v.id not in drop_ids]
        es = [e for e in self.edges if e.src not in drop_ids and e.tgt not in drop_ids]
        return MutationGraph(target_id=self.target_id, vertices=vs, edges=es,
                             classes_total=self.classes_total)

    def focus(self, *, failing_tests=None, k_methods: int = 6,
              class_cap: "int | None" = None) -> "MutationGraph":
        """A prompt-sized MutationGraph (the MVP 'HGT ranker -> top-k' relevance
        filter — the raw GT graph is ~90 methods / 1400 tests). Keeps: the target +
        its direct CALLS callers (methods with an edge into the target), capped to
        k_methods by caller-edge count; test/assert vertices restricted to
        `failing_tests` (fqn set) when given, else all; edges among kept vertices;
        then the class cap. Deterministic + leak-safe."""
        tgt = self.target_id
        caller_ids = [e.src for e in self.edges
                      if e.tgt == tgt and e.type in ("CALLS", "DATA_DEP")
                      and (self.vertex(e.src) or MgVertex("", "", "")).type == "method"]
        by_count: dict = {}
        for cid in caller_ids:
            by_count[cid] = by_count.get(cid, 0) + 1
        top_callers = [c for c, _ in sorted(by_count.items(),
                                            key=lambda kv: (-kv[1], kv[0]))[:k_methods]]
        keep_methods = {tgt, *top_callers}
        fset = set(failing_tests) if failing_tests else None
        keep_tests = {v.id for v in self.vertices if v.type in ("test", "assert")
                      and (fset is None or v.fqn in fset)}
        keep = keep_methods | keep_tests
        vs = [v for v in self.vertices if v.id in keep]
        es = [e for e in self.edges if e.src in keep and e.tgt in keep]
        g = MutationGraph(target_id=tgt, vertices=vs, edges=es)
        return g.with_class_cap(class_cap)
```

- [ ] **Step 4: Run** `python3 -m pytest tests/test_rcc_mutation_graph.py -q` — 5 passed (add the focus test below).

Add this test to `tests/test_rcc_mutation_graph.py`:

```python
def test_focus_keeps_target_callers_and_failing_tests():
    vs = [MgVertex(id="method:t", type="method", fqn="p.C.t", is_changed=True),
          MgVertex(id="method:caller", type="method", fqn="p.C.caller"),
          MgVertex(id="method:far", type="method", fqn="p.C.far"),
          MgVertex(id="test:p.T.f", type="test", fqn="p.T.f"),
          MgVertex(id="test:p.T.ok", type="test", fqn="p.T.ok")]
    es = [MgEdge(src="method:caller", tgt="method:t", type="CALLS"),
          MgEdge(src="method:far", tgt="method:caller", type="CALLS"),
          MgEdge(src="test:p.T.f", tgt="method:t", type="TEST_ASSERTS"),
          MgEdge(src="test:p.T.ok", tgt="method:t", type="TEST_ASSERTS")]
    g = MutationGraph(target_id="method:t", vertices=vs, edges=es)
    f = g.focus(failing_tests={"p.T.f"}, k_methods=6)
    assert set(f.methods()) == {"p.C.t", "p.C.caller"}     # target + direct caller; 'far' dropped
    assert f.test_fqns == ["p.T.f"]                          # only the failing test
```

- [ ] **Step 5: Commit**

```bash
git add abench/rcc_mutation_graph.py tests/test_rcc_mutation_graph.py
git commit -m "feat(rcc): typed MutationGraph model (R1) — method/test vertices, typed edges"
```

---

### Task 2: `parse_gt_graph` — GT output → MutationGraph (leak-safe)

**Files:**
- Create: `abench/rcc_gt_parse.py`
- Test: `tests/test_rcc_gt_parse.py`

- [ ] **Step 1: Write the failing tests** (against the committed gt-out sample + a synthetic minimal graph)

```python
# tests/test_rcc_gt_parse.py
import json
from pathlib import Path

from abench.rcc_gt_parse import parse_gt_graph

_GT_SAMPLE = Path("experiments/picocli-putValue/gt-out/slice-work/"
                  "357b6bd1af378e00.graph.json")


def _mini():
    return {
        "target": {"fqn": "p.C.put", "signature": "Cell(int,int)",
                   "file": "C.java", "line_start": 10, "line_end": 20,
                   "current_body": "SECRET CORRECT IMPL"},
        "method_bodies": {
            "p.C.get": {"fqn": "p.C.get", "signature": "Object()",
                        "file": "C.java", "line_start": 30, "line_end": 33,
                        "sliced_body": "Object get(){...}"},
        },
        "chains": [
            {"id": "c0", "depth": 2, "test": {"fqn": "p.CT.t1", "file": "T.java",
                                              "line": 5, "sliced_body": "assertX()"},
             "steps": [
                 {"caller_ref": "test", "callee_ref": "p.C.get",
                  "call_site": {"file": "T.java", "line": 5, "code": "c.get()"},
                  "args": [], "virtual": False},
                 {"caller_ref": "p.C.get", "callee_ref": "target",
                  "call_site": {"file": "C.java", "line": 31, "code": "put(r,c,v)"},
                  "args": [{"index": 0, "origin": "param", "value": "r"}],
                  "virtual": False},
             ]},
        ],
    }


def test_parse_drops_target_correct_body():
    g = parse_gt_graph(_mini())
    tv = g.vertex(g.target_id)
    assert tv.fqn == "p.C.put" and tv.is_changed is True
    assert tv.source is None                       # current_body NEVER kept (leak)
    assert "SECRET" not in json.dumps([v.__dict__ for v in g.vertices])


def test_parse_builds_typed_vertices_and_edges():
    g = parse_gt_graph(_mini())
    assert g.target_fqn == "p.C.put"
    assert set(g.methods()) == {"p.C.put", "p.C.get"}
    assert g.test_fqns == ["p.CT.t1"]
    # neighbor body kept (legit), test body kept
    assert g.vertex("method:p.C.get").source == "Object get(){...}"
    # chain steps -> CALLS edges (refs resolved: test->test vertex, target->target)
    calls = {(e.src, e.tgt) for e in g.edges if e.type == "CALLS"}
    assert ("test:p.CT.t1", "method:p.C.get") in calls
    assert ("method:p.C.get", "method:p.C.put") in calls
    # each test asserts the target
    assert any(e.type == "TEST_ASSERTS" and e.src == "test:p.CT.t1"
               and e.tgt == "method:p.C.put" for e in g.edges)


def test_target_source_override_is_used_when_given():
    g = parse_gt_graph(_mini(), target_source="AGENT ATTEMPT BODY")
    assert g.vertex(g.target_id).source == "AGENT ATTEMPT BODY"


def test_parses_the_real_committed_gt_sample():
    if not _GT_SAMPLE.is_file():
        import pytest
        pytest.skip("gt-out sample not present")
    g = parse_gt_graph(json.loads(_GT_SAMPLE.read_text()))
    assert "putValue" in g.target_fqn
    assert g.vertex(g.target_id).source is None            # correct body stripped
    assert len(g.methods()) > 3 and len(g.test_fqns) > 10   # real structure present
    assert any(e.type == "CALLS" for e in g.edges)
```

- [ ] **Step 2: Run** `python3 -m pytest tests/test_rcc_gt_parse.py -q` — FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `abench/rcc_gt_parse.py`**

```python
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

    # target vertex — current_body is the leak; NEVER stored. target_source (the
    # agent's workdir body) is used when the GT builder runs on the workdir.
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
        return _method_id(ref)          # an intermediate method fqn

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
            # arg data-flow from a param/upstream call → a DATA_DEP hint into callee
            for a in st.get("args") or []:
                if a.get("origin") in ("param", "method_call"):
                    add_edge(src, dst, "DATA_DEP",
                             data_var=str(a.get("value") or a.get("expr") or a.get("index")))
        # the test's assertion checks the target's behaviour
        add_edge(_test_id(t_fqn), target_id, "TEST_ASSERTS")

    return MutationGraph(target_id=target_id, vertices=vertices, edges=edges)
```

- [ ] **Step 4: Run** `python3 -m pytest tests/test_rcc_gt_parse.py -q` — 4 passed (the real-sample test runs since the file is committed).

- [ ] **Step 5: Commit**

```bash
git add abench/rcc_gt_parse.py tests/test_rcc_gt_parse.py
git commit -m "feat(rcc): parse GT graph.json -> MutationGraph, target correct-body stripped (R1)"
```

---

### Task 3: build seam + LLM builder + GT adapter

**Files:**
- Create: `abench/rcc_mgraph_build.py`
- Test: `tests/test_rcc_mgraph_build.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_rcc_mgraph_build.py
import json

from abench.rcc_mgraph_build import llm_builder, parse_mgraph_json


_MG_JSON = {
    "vertices": [
        {"id": "method:p.C.put", "type": "method", "fqn": "p.C.put",
         "is_changed": True, "signature": "Cell(int,int)"},
        {"id": "method:p.C.get", "type": "method", "fqn": "p.C.get"},
        {"id": "test:p.CT.t1", "type": "test", "fqn": "p.CT.t1"},
    ],
    "edges": [
        {"src": "method:p.C.put", "tgt": "method:p.C.get", "type": "CALLS"},
        {"src": "test:p.CT.t1", "tgt": "method:p.C.put", "type": "TEST_ASSERTS"},
    ],
    "target_id": "method:p.C.put",
}


def test_parse_mgraph_json_from_prose():
    g = parse_mgraph_json("here:\n" + json.dumps(_MG_JSON) + "\nend")
    assert g.target_fqn == "p.C.put"
    assert set(g.methods()) == {"p.C.put", "p.C.get"}
    assert g.test_fqns == ["p.CT.t1"]


def test_parse_mgraph_json_rejects_garbage():
    assert parse_mgraph_json("no json") is None
    assert parse_mgraph_json('{"vertices": "x", "edges": []}') is None
    assert parse_mgraph_json("") is None


def test_llm_builder_calls_phase_runner_and_parses():
    from abench.orchestrator import PhaseOutcome
    from abench.trace_model import Trace
    calls = []

    def fake_phase(phase, prompt, tools):
        calls.append((phase, tuple(tools)))
        return PhaseOutcome(trace=Trace(), text=json.dumps(_MG_JSON))

    g = llm_builder("/wd", "p.C.put", {"p.C.put": ["p.CT.t1"]},
                    phase_runner=fake_phase)
    assert g is not None and g.target_fqn == "p.C.put"
    assert calls and calls[0][0] == "build_graph"


def test_llm_builder_returns_none_on_unparseable():
    from abench.orchestrator import PhaseOutcome
    from abench.trace_model import Trace

    def fake_phase(phase, prompt, tools):
        return PhaseOutcome(trace=Trace(), text="sorry, no graph")

    assert llm_builder("/wd", "p.C.put", {}, phase_runner=fake_phase) is None
```

- [ ] **Step 2: Run** `python3 -m pytest tests/test_rcc_mgraph_build.py -q` — FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `abench/rcc_mgraph_build.py`**

```python
"""The build_mutation_graph seam (R1) + its builders.

The graph is ALWAYS built from the agent's workdir (leak-safe). Two builders:
- gt_kgpool_builder: subprocess to Graph-Tipper's kgpool on the workdir (primary,
  high fidelity, runs where GT is installed — the prepared box). abench CONSUMES
  GT's graph.json; it never modifies GT.
- llm_builder: one phase_runner call reading the diff + files + coverage hint →
  MutationGraph JSON (in-repo fallback; no external dep).
Selection: explicit `builder=` or an env/config knob in the Phase-2 wiring."""
from __future__ import annotations

import json

from .rcc_mutation_graph import MgEdge, MgVertex, MutationGraph


def parse_mgraph_json(text: "str | None") -> "MutationGraph | None":
    """First JSON object in `text` with list vertices+edges → MutationGraph."""
    if not text:
        return None
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = dec.raw_decode(text[i:])
        except ValueError:
            continue
        if (isinstance(obj, dict) and isinstance(obj.get("vertices"), list)
                and isinstance(obj.get("edges"), list)):
            return _from_json(obj)
    return None


def _from_json(obj: dict) -> MutationGraph:
    vertices = []
    for v in obj["vertices"]:
        if not isinstance(v, dict) or not v.get("id"):
            continue
        vertices.append(MgVertex(
            id=str(v["id"]), type=v.get("type", "method"), fqn=v.get("fqn", ""),
            location=v.get("location"), is_changed=bool(v.get("is_changed")),
            l1_skeleton=({"signature": v["signature"]} if v.get("signature")
                         else v.get("l1_skeleton")),
            source=v.get("source")))
    edges = []
    for e in obj["edges"]:
        if isinstance(e, dict) and e.get("src") and e.get("tgt"):
            edges.append(MgEdge(src=str(e["src"]), tgt=str(e["tgt"]),
                                type=e.get("type", "CALLS"),
                                call_site=e.get("call_site"), data_var=e.get("data_var")))
    target_id = obj.get("target_id") or next(
        (v.id for v in vertices if v.is_changed), vertices[0].id if vertices else "")
    return MutationGraph(target_id=target_id, vertices=vertices, edges=edges)


def _build_graph_prompt(target_fqn: str, coverage: dict) -> str:
    tests = sorted({t for ts in (coverage or {}).values() for t in ts})[:60]
    hint = "\n".join(f"- {t}" for t in tests) or "(none)"
    return (
        "Build a MUTATION GRAPH for the code change under repair: the call/dataflow "
        f"structure from the changed method {target_fqn} up to the JUnit asserts that "
        "exercise it. Read the diff and the relevant source. Return ONLY a JSON object:\n"
        '{"target_id": "method:<fqn>", '
        '"vertices": [{"id": "method:<fqn>|test:<fqn>", "type": "method|test|assert", '
        '"fqn": <fqn>, "is_changed": <bool>, "signature": <str>}], '
        '"edges": [{"src": <id>, "tgt": <id>, '
        '"type": "CALLS|DATA_DEP|CONTROL_DEP|TEST_ASSERTS|OVERRIDES", '
        '"call_site": {"file":..,"line":..}, "data_var": <str>}]}.\n'
        "Mark the changed method is_changed=true. Include the tests that assert it "
        "(TEST_ASSERTS edges). Candidate covering tests (from coverage data):\n" + hint)


def llm_builder(workdir, target_fqn, coverage, *, phase_runner) -> "MutationGraph | None":
    """Fallback builder: one LLM call → MutationGraph. None if unparseable (caller
    then degrades to plain phased)."""
    out = phase_runner("build_graph", _build_graph_prompt(target_fqn, coverage),
                       ["read", "grep"])
    return parse_mgraph_json(getattr(out, "text", None))


def gt_kgpool_builder(workdir, target_fqn, coverage, *, gt_home, timeout_s=600,
                      runner=None) -> "MutationGraph | None":
    """Primary builder: run Graph-Tipper's kgpool on the WORKDIR (agent's code) +
    target, parse its graph.json into a MutationGraph. Runs where GT is installed.
    `runner` is injected for tests; real runs shell out. Best-effort — None on any
    failure (caller degrades to plain phased)."""
    import subprocess
    from pathlib import Path

    from .rcc_gt_parse import parse_gt_graph

    def _default_runner(cmd, cwd, env):
        return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True,
                              text=True, timeout=timeout_s)
    runner = runner or _default_runner
    try:
        # NOTE: the exact kgpool entrypoint/flag for a WORKDIR-structural graph
        # (vs the reference-tipper mode) is unconfirmed — verify on the box and
        # adjust these args. The workdir target body is the agent's own code, so
        # it is passed through as target_source (leak-safe).
        out_dir = Path(workdir) / ".rcc-graph"
        cmd = ["python3", "-m", "harness.kgpool.make", "--project", str(workdir),
               "--target", target_fqn, "--out", str(out_dir), "--skip-jacoco",
               "--structural"]
        import os
        env = dict(os.environ, PYTHONPATH=str(gt_home))
        runner(cmd, str(gt_home), env)
        gj = json.loads((out_dir / "graph.json").read_text())
        tsrc = (gj.get("target") or {}).get("current_body")   # workdir body = agent's
        return parse_gt_graph(gj, target_source=tsrc)
    except Exception:
        return None


def build_mutation_graph(workdir, target_fqn, coverage, *, builder="llm", **kw):
    """Dispatch to the selected builder. 'gt' needs gt_home; 'llm' needs phase_runner."""
    if builder == "gt":
        return gt_kgpool_builder(workdir, target_fqn, coverage, **kw)
    return llm_builder(workdir, target_fqn, coverage, **kw)
```

Note on the GT builder's `current_body`: when kgpool runs on the WORKDIR, `target.current_body` is the agent's own attempt (leak-safe) → passed as `target_source`. This is the opposite of the fixture (reference-built), where the parser is called WITHOUT an override so the correct body is dropped. The `--structural` flag is a placeholder pending the box check (R1 open item); if kgpool lacks it, this builder waits and `llm` stays primary.

- [ ] **Step 4: Run** `python3 -m pytest tests/test_rcc_mgraph_build.py -q` — 4 passed. (The GT builder is not unit-tested here — it's an adapter validated on the box; Task 3 covers the parse + LLM paths that run on Mac.)

- [ ] **Step 5: Commit**

```bash
git add abench/rcc_mgraph_build.py tests/test_rcc_mgraph_build.py
git commit -m "feat(rcc): build_mutation_graph seam — llm builder + GT kgpool adapter (R1)"
```

---

### Task 4: Alpha — vertex + edge contracts over MutationGraph

**Files:**
- Rewrite: `abench/rcc_prompts.py` (this task: `alpha_prompt`, `beta_prompt`, `beta_repair_prompt`, the `_graph_block` helper, constants; Gamma/rank come in Task 5)
- Test: rewrite `tests/test_rcc_prompts.py` (Alpha/Beta portion)

- [ ] **Step 1: Write the failing tests** (start the rewritten file; Gamma tests appended in Task 5)

```python
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
```

- [ ] **Step 2: Run** — FAIL (`ImportError`, module about to be rewritten).

- [ ] **Step 3: Implement** — rewrite the TOP of `abench/rcc_prompts.py` (imports, constants, helpers, Alpha, Beta). Replace `from .rcc_subgraph import RccSubgraph` with `from .rcc_mutation_graph import MutationGraph`. Keep `PROBE_MARKER`, `PROBE_PREFIX`, `_MAX_*`, `GAMMA_FORMAT_REMINDER`, and `_cap`/`_fmt_cluster` imports from `.orchestrator`. New graph rendering + Alpha/Beta:

```python
def _vertices_block(g: MutationGraph) -> str:
    parts = []
    for fqn in g.methods():
        v = next((x for x in g.vertices if x.type == "method" and x.fqn == fqn), None)
        sig = (v.l1_skeleton or {}).get("signature", "") if v else ""
        src = (v.source if v else "") or "(source unavailable — read it yourself)"
        tag = " [CHANGED]" if v and v.is_changed else ""
        parts.append(f"### {fqn}{tag}  {sig}\n```java\n{src}\n```")
    return "\n".join(parts)


def _edges_block(g: MutationGraph) -> str:
    rows = []
    for e in g.edges:
        s = g.vertex(e.src); t = g.vertex(e.tgt)
        sn = s.fqn if s else e.src; tn = t.fqn if t else e.tgt
        extra = ""
        if e.type == "CALLS" and e.call_site:
            extra = f" @ {e.call_site.get('file')}:{e.call_site.get('line')} " \
                    f"`{e.call_site.get('code','')}`"
        elif e.type == "DATA_DEP" and e.data_var:
            extra = f" [{e.data_var}]"
        rows.append(f"- {sn} --{e.type}--> {tn}{extra}")
    return "\n".join(rows) or "(no edges)"


def alpha_prompt(g: MutationGraph) -> str:
    return (
        "You are writing CONTRACTS over a MUTATION GRAPH (the call/dataflow structure "
        f"from the changed method {g.target_fqn} to the tests that assert it).\n\n"
        "For EACH METHOD vertex write a vertex contract:\n"
        "- pre / post / inv (reference the signature + the source shown).\n"
        "For EACH CALLS / DATA_DEP EDGE write an interaction contract:\n"
        "- what the caller expects of the callee at that call site, and how the "
        "callee's result/effect must be used (for DATA_DEP: the constraint on the "
        "flowing variable).\n"
        "Base everything on the source + structure. Do NOT edit code.\n\n"
        "VERTICES:\n" + _vertices_block(g) + "\n\nEDGES:\n" + _edges_block(g))


def beta_prompt(g: MutationGraph, specs_text: str) -> str:
    return (
        "Instrument the code for INVASIVE DEBUGGING to check the contracts against "
        "actual runtime values. Insert System.out.println lines into the methods "
        "below. EVERY inserted line must:\n"
        f"- start its message with \"{PROBE_PREFIX} <Class.method>: \" and print the "
        "arguments at entry, the return value at exit, and key branch state;\n"
        f"- end with the trailing comment {PROBE_MARKER} on the SAME line;\n"
        "- change NO behaviour and keep the code compiling.\n\n"
        "CONTRACTS to check:\n" + _cap(specs_text, _MAX_SPECS_CHARS)
        + "\n\nMETHODS:\n" + _vertices_block(g))


def beta_repair_prompt(g: MutationGraph) -> str:
    return (
        "The instrumented build no longer compiles. Fix the compilation — delete a "
        f"probe line rather than leave the build broken. Every probe line keeps its "
        f"trailing {PROBE_MARKER} comment. Do not change program logic.")
```

- [ ] **Step 4: Run** `python3 -m pytest tests/test_rcc_prompts.py -q` — the Alpha/Beta tests pass (Gamma imports still missing → those tests not added yet). Confirm the two written tests pass.

- [ ] **Step 5: Commit**

```bash
git add abench/rcc_prompts.py tests/test_rcc_prompts.py
git commit -m "feat(rcc): Alpha over MutationGraph — vertex + edge (interaction) contracts (R1)"
```

---

### Task 5: Gamma CausalDeltaSubGraph + CausalRank(root-cause×confidence)

**Files:**
- Modify: `abench/rcc_prompts.py` (append: `gamma_prompt`, `fix_prompt`, `cache_fix_prompt`, `parse_causal_delta`, `causal_rank`, `root_rank`)
- Test: append to `tests/test_rcc_prompts.py`

- [ ] **Step 1: Write the failing tests** — append:

```python
import json

from abench.rcc_prompts import (cache_fix_prompt, causal_rank, fix_prompt,
                                gamma_prompt, parse_causal_delta, root_rank)

_CDG = {
    "vertices": [
        {"id": "cd1", "mutation_vertex": "method:p.C.put", "type": "root_cause",
         "spec_text": "put must return non-null", "violated": True,
         "is_root_cause": True, "confidence": 0.96, "runtime_value": "ret=null"},
        {"id": "cd2", "mutation_vertex": "method:p.C.get", "type": "downstream_effect",
         "violated": True, "is_root_cause": False, "confidence": 0.9},
    ],
    "edges": [{"from": "cd1", "to": "cd2", "type": "CAUSES",
               "path": ["method:p.C.put", "method:p.C.get"], "reasoning": "null propagates"}],
}


def test_gamma_prompt_asks_for_causal_delta_schema():
    g = _g()
    p = gamma_prompt(g, "SPECS", ["RCC_PROBE put: ret=null"])
    assert "CausalDeltaSubGraph" in p or "is_root_cause" in p
    assert "ret=null" in p and "mutation_vertex" in p
    assert "no runtime logs" in gamma_prompt(g, "S", [])


def test_parse_causal_delta_from_prose_and_reject_garbage():
    assert parse_causal_delta("x " + json.dumps(_CDG) + " y")["vertices"][0]["confidence"] == 0.96
    assert parse_causal_delta("nope") is None
    assert parse_causal_delta('{"vertices": 1, "edges": []}') is None


def test_causal_rank_by_root_cause_then_confidence():
    g = _g()
    ranks = causal_rank(_CDG, g.methods())
    assert ranks[0][0] == "p.C.put"                    # is_root_cause wins
    assert root_rank(ranks, "p.C.put") == 1
    # degraded (no graph) keeps mutation-graph order (target first)
    assert causal_rank(None, g.methods())[0][0] == "p.C.put"


def test_fix_prompt_and_cache_fix_carry_the_delta():
    g = _g()
    f = fix_prompt("the put method", "p.C.put", _CDG, "SPECS", [], "p.C.put", 1)
    assert "root" in f.lower() and "CAUSES" in f
    c = cache_fix_prompt("the put method", _CDG, [])
    assert "previous successful" in c and "is_root_cause" in c
```

- [ ] **Step 2: Run** — FAIL (`ImportError` for the new names).

- [ ] **Step 3: Implement** — append to `abench/rcc_prompts.py`:

```python
def gamma_prompt(g: MutationGraph, specs_text: str, probe_lines: list) -> str:
    logs = "\n".join((probe_lines or [])[:_MAX_LOG_LINES]) \
        or "(no runtime logs — instrumentation was skipped)"
    mids = "\n".join(f"- {v.id} ({v.fqn})" for v in g.vertices if v.type == "method")
    return (
        "Build a CausalDeltaSubGraph: compare each method/edge CONTRACT against the "
        "runtime PROBE LOGS and mark violations, root cause, and downstream effects.\n"
        "Return ONLY JSON:\n"
        '{"vertices": [{"id": <str>, "mutation_vertex": <mutation-graph vertex id>, '
        '"type": "root_cause|downstream_effect|spec_violation|unaffected", '
        '"spec_text": <str>, "spec_level": "L1|L2|L3", "runtime_value": <any>, '
        '"violated": <bool>, "is_root_cause": <bool>, "confidence": <0..1>}], '
        '"edges": [{"from": <id>, "to": <id>, '
        '"type": "CAUSES|CONTRIBUTES_TO|DATA_FLOWS_INTO|CONTRACT_REFINES", '
        '"path": [<mutation vertex ids>], "reasoning": <str>}]}.\n'
        "Exactly one vertex should have is_root_cause=true (the deepest violated "
        "contract that explains the cascade). mutation_vertex MUST be one of:\n"
        + mids + "\n\nCONTRACTS:\n" + _cap(specs_text, _MAX_SPECS_CHARS)
        + "\n\nPROBE LOGS:\n" + logs)


def _cdg_txt(graph) -> str:
    return (_cap(json.dumps(graph, indent=1), _MAX_GRAPH_CHARS) if graph
            else "(no causal graph — analysis degraded; rely on failures + contracts)")


def fix_prompt(target_label, target_fqn, graph, specs_text, clusters, focus_fqn,
               attempt) -> str:
    body = "\n".join(_fmt_cluster(c) for c in clusters) or "(no parsed clusters)"
    focus = (f"The causal analysis marks {focus_fqn} as the ROOT CAUSE."
             if focus_fqn == target_fqn else
             f"The causal analysis points at {focus_fqn}; trace how it breaks {target_fqn}.")
    retry = ("" if attempt == 1 else
             "\nYour previous fix did NOT go green — take a different angle.")
    return (f"Fix the ROOT CAUSE with ONE change to {target_label}.{retry}\n{focus}\n\n"
            f"CAUSAL DELTA GRAPH:\n{_cdg_txt(graph)}\n\nFAILURE CLUSTERS:\n{body}\n\n"
            f"CONTRACTS (reference):\n{_cap(specs_text, _MAX_SPECS_CHARS)}")


def cache_fix_prompt(target_label, graph, clusters) -> str:
    body = "\n".join(_fmt_cluster(c) for c in clusters) or "(no parsed clusters)"
    return (f"A previous successful debugging session of {target_label} produced this "
            "CausalDeltaSubGraph. Apply the SAME root-cause fix.\n\nCAUSAL DELTA "
            f"(cached):\n{_cdg_txt(graph)}\n\nCURRENT FAILURES:\n{body}")


def parse_causal_delta(text):
    if not text:
        return None
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = dec.raw_decode(text[i:])
        except ValueError:
            continue
        if (isinstance(obj, dict) and isinstance(obj.get("vertices"), list)
                and isinstance(obj.get("edges"), list)):
            return obj
    return None


def _num(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def causal_rank(graph, methods):
    """Rank method FQNs by (is_root_cause, confidence) of their CausalDeltaSubGraph
    vertex, tie-broken by mutation-graph order (target first). A None/empty graph
    returns mutation-graph order with 0.0 — the degraded ranking."""
    order = {m: i for i, m in enumerate(methods)}
    score: dict = {m: (0, 0.0) for m in methods}
    for v in (graph or {}).get("vertices", []) or []:
        if not isinstance(v, dict):
            continue
        mv = str(v.get("mutation_vertex") or "")
        fqn = mv.split(":", 1)[1] if mv.startswith("method:") else mv
        if fqn not in score:
            fqn = next((m for m in methods if m == v.get("fqn")), None)
        if fqn in score:
            rc = 1 if v.get("is_root_cause") else 0
            score[fqn] = max(score[fqn], (rc, _num(v.get("confidence"))))
    return sorted(((m, score[m][1]) for m in methods),
                  key=lambda kv: (-score[kv[0]][0], -score[kv[0]][1], order[kv[0]]))


def root_rank(ranks, target_fqn):
    for i, (m, _s) in enumerate(ranks, 1):
        if m == target_fqn:
            return i
    return None
```

- [ ] **Step 4: Run** `python3 -m pytest tests/test_rcc_prompts.py -q` — all pass.

- [ ] **Step 5: Commit**

```bash
git add abench/rcc_prompts.py tests/test_rcc_prompts.py
git commit -m "feat(rcc): Gamma CausalDeltaSubGraph + CausalRank by root-cause x confidence (R1)"
```

---

### Task 6: rewire `rcc_graph.py` to MutationGraph + delete the old subgraph

**Files:**
- Modify: `abench/rcc_graph.py`
- Delete: `abench/rcc_subgraph.py`, `tests/test_rcc_subgraph.py`
- Modify: `tests/test_rcc_graph.py` (fixtures + build seam)

- [ ] **Step 1: Update the graph tests' fixtures** — in `tests/test_rcc_graph.py`, replace the `RccSubgraph` import + `_SUB` with a `MutationGraph`, and pass a `mutation_graph=` (or `build_graph=`) into `run_rcc`. New top-of-file fixture:

```python
from abench.rcc_mutation_graph import MgEdge, MgVertex, MutationGraph

_SUB = MutationGraph(
    target_id="method:p.C.put",
    vertices=[MgVertex(id="method:p.C.put", type="method", fqn="p.C.put",
                       is_changed=True, source="Cell put(){ return null; }"),
              MgVertex(id="method:p.C.get", type="method", fqn="p.C.get",
                       source="Object get(){...}"),
              MgVertex(id="test:p.CT.t1", type="test", fqn="p.CT.t1"),
              MgVertex(id="test:p.CT.t2", type="test", fqn="p.CT.t2")],
    edges=[MgEdge(src="method:p.C.put", tgt="method:p.C.get", type="CALLS"),
           MgEdge(src="test:p.CT.t1", tgt="method:p.C.put", type="TEST_ASSERTS"),
           MgEdge(src="test:p.CT.t2", tgt="method:p.C.put", type="TEST_ASSERTS")],
)
```

Update `_GAMMA` to a CausalDeltaSubGraph literal:

```python
_GAMMA = json.dumps({
    "vertices": [{"id": "cd1", "mutation_vertex": "method:p.C.put",
                  "type": "root_cause", "is_root_cause": True, "confidence": 0.95,
                  "violated": True, "runtime_value": "ret=null"},
                 {"id": "cd2", "mutation_vertex": "method:p.C.get",
                  "type": "downstream_effect", "is_root_cause": False,
                  "confidence": 0.9, "violated": True}],
    "edges": [{"from": "cd1", "to": "cd2", "type": "CAUSES",
               "path": ["method:p.C.put", "method:p.C.get"], "reasoning": "null propagates"}],
})
```

The event assertion `"CausalRank of target = 1/2"` in `test_green_on_top1` still holds (target ranks first via is_root_cause). `_SUB.methods` → `_SUB.methods()` wherever the tests call it — update those call sites (the graph exposes `methods()` as a method now, and `test_classes`/`test_fqns` as properties).

- [ ] **Step 2: Run** `python3 -m pytest tests/test_rcc_graph.py -q` — FAIL (rcc_graph.py still imports/uses `RccSubgraph`, `parse_gamma`, old `causal_rank`).

- [ ] **Step 3: Rewire `abench/rcc_graph.py`:**

1. Imports: replace `from .rcc_subgraph import RccSubgraph` → `from .rcc_mutation_graph import MutationGraph`; replace `parse_gamma` → `parse_causal_delta`; `causal_rank`/`root_rank` come from `rcc_prompts` (already). The `sub` parameter type becomes `MutationGraph`; every `sub.methods` → `sub.methods()`, `sub.test_classes`/`sub.test_fqns` stay (properties).

2. `memory_node` / all nodes that read `sub.methods` — call `sub.methods()`.

3. `gamma_node` — swap `parse_gamma` → `parse_causal_delta`; keep the retry/degrade shape; the rank event text and `root_rank` are unchanged in meaning (now driven by the CausalDeltaSubGraph).

4. `run_rcc` signature — the mutation graph arrives via the existing `sub` param; Phase-2 wiring passes `build_mutation_graph(...)` result. No new required arg (the build happens in the Phase-2 runner / prefix driver, keeping `run_rcc` graph-agnostic and the fake tests injecting `_SUB` directly). Add ONE controller event at the start naming the graph: `f"mutation graph: {len(sub.methods())} methods, {len(sub.edges)} edges, {len(sub.test_fqns)} tests"`.

- [ ] **Step 4: Delete the superseded module + its test**

```bash
git rm abench/rcc_subgraph.py tests/test_rcc_subgraph.py
```

Then `grep -rn "rcc_subgraph\|shared_test_edges\|RccSubgraph" abench/ tests/` — expect ZERO hits (Phase-2 plan references update in Task 7).

- [ ] **Step 5: Run the full rcc sweep** `python3 -m pytest tests/ -q -k "rcc"` — all pass.

- [ ] **Step 6: Full suite** `python3 -m pytest tests/ -q` — green except the known pre-existing `test_robustness` failure.

- [ ] **Step 7: Commit**

```bash
git add abench/rcc_graph.py tests/test_rcc_graph.py
git commit -m "refactor(rcc): rewire the loop to MutationGraph + CausalDeltaSubGraph; drop coverage-overlap subgraph (R1)"
```

---

### Task 7: reconcile the Phase-2 wiring plan with R1

**Files:**
- Modify: `docs/superpowers/plans/2026-07-08-rcc-phase2-wiring.md`

- [ ] **Step 1: Patch the Phase-2 plan** so its runner-dispatch task builds the graph via the seam instead of the deleted `build_subgraph`. In that plan's Task 5, replace the `build_subgraph(...)` call with:

```python
                        from .rcc_mgraph_build import build_mutation_graph
                        # builder: 'gt' where Graph-Tipper is installed (env/knob),
                        # else 'llm' (in-repo). Both build on the workdir (leak-safe).
                        builder = os.environ.get("ABENCH_RCC_GRAPH_BUILDER", "llm")
                        bkw = ({"gt_home": os.environ["GRAPH_TIPPER_HOME"]}
                               if builder == "gt" else {"phase_runner": phase_runner})
                        mg = build_mutation_graph(workdir, (exp.target_methods or [""])[0],
                                                  _load_coverage(workdir), builder=builder, **bkw)
                        sub = mg.with_class_cap(ocfg.rcc_subset_class_cap or None) if mg else None
```

and note that `rcc_subgraph_k` is retired (the graph builder decides scope, not a top-K); `rcc_subset_class_cap` now applies via `MutationGraph.with_class_cap`. Add a one-line `_load_coverage(workdir)` helper reading `.impact/coverage.json` (tolerant, `{}` on absence). Leave the rest of Phase-2 (telemetry, A/B YAML, hit demo) unchanged — the node signatures held.

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-07-08-rcc-phase2-wiring.md
git commit -m "docs(plan): reconcile Phase-2 wiring with the R1 build_mutation_graph seam"
```

---

## Self-review

- **Spec coverage:** R1.1 MutationGraph → Task 1; R1.2 build seam (GT + LLM) → Task 3; R1.3 Alpha edge contracts → Task 4; R1.4 Gamma CausalDeltaSubGraph → Task 5; R1.5 CausalRank → Task 5; R1.6 unchanged pieces → preserved in Task 6; R1.7 fixture/testing → Tasks 2, 5, 6; leak-safety invariant → enforced structurally in Task 2 (`parse_gt_graph` cannot emit `current_body`) + the workdir-only builders in Task 3.
- **Placeholder scan:** none — the only deliberate unknown is the GT `--structural` flag (R1 open item), flagged inline in Task 3 with the fallback path (`llm` stays primary) so it does not block execution.
- **Type consistency:** `MutationGraph.methods()` is a method (call sites updated in Tasks 4–6); `test_fqns`/`test_classes`/`classes_total` are properties/fields; `parse_causal_delta` replaces `parse_gamma`; `causal_rank(graph, methods)` keeps its 2-arg shape (graph is now a CausalDeltaSubGraph dict, `None`→degraded); `build_mutation_graph(workdir, target_fqn, coverage, *, builder, **kw)` is the single seam entry.

## Out of scope

The real GT kgpool workdir-structural mode confirmation + the `--structural` flag (box check — R1 open item); Joern-per-invocation cost measurement + content-hash caching; running the A/B itself; the parser (javaparser) third builder; escalation / semantic memory (Phase 3).
