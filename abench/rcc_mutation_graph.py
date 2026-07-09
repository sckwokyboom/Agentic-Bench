"""RapidCausalCoder R1 — the typed mutation graph (call/dataflow structure).

Vertices are methods / tests / asserts; edges are CALLS / DATA_DEP / CONTROL_DEP /
TEST_ASSERTS / OVERRIDES. This is the structural backbone Alpha/Gamma reason over
(replaces the old coverage-overlap flat list). Always built from the AGENT's
workdir (see rcc_mgraph_build) — never ground truth. Pure data + derivations."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MgVertex:
    id: str                                  # "method:fqn" | "test:fqn" | "assert:..."
    type: str                                # "method" | "test" | "assert"
    fqn: str
    location: "dict | None" = None           # {file, line_start, line_end}
    is_changed: bool = False                 # directly modified by the diff
    l1_skeleton: "dict | None" = None        # {signature, params, return_type, local_vars}
    source: "str | None" = None              # body FROM THE WORKDIR (leak-safe)
    status: "str | None" = None      # tests: "failed" | "passing" | "unknown_reachable"


@dataclass
class MgEdge:
    src: str
    tgt: str
    type: str                                # CALLS|DATA_DEP|CONTROL_DEP|TEST_ASSERTS|OVERRIDES
    call_site: "dict | None" = None          # {file, line, code} for CALLS
    data_var: "str | None" = None            # for DATA_DEP
    # R2: structural is the call/assert direction; influence is causal-propagation
    # direction (a method's behaviour influences the tests that assert it). path_ids
    # link an edge to the call chains it belongs to. test_status mirrors the chain's
    # test. source = provenance ("gt" | "llm").
    structural_direction: "str | None" = None
    influence_direction: "str | None" = None
    path_ids: list = field(default_factory=list)
    test_status: "str | None" = None
    source: str = "gt"


@dataclass
class MgChain:
    """A call chain (path) test → … → target from the GT graph. `node_ids` are
    vertex ids ordered test-first; `status` mirrors the chain's test."""
    id: str
    test_fqn: str
    node_ids: list = field(default_factory=list)
    status: "str | None" = None


@dataclass
class MutationGraph:
    target_id: str
    vertices: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    classes_total: int = 0                   # distinct test classes BEFORE any class cap
    chains: list = field(default_factory=list)          # [MgChain]
    stats: dict = field(default_factory=dict)           # GraphRaw summary counts
    change_origin: dict = field(default_factory=dict)   # {kind, method_fqn, changed_statement_available}

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
        its direct CALLS/DATA_DEP callers (method vertices with an edge into the
        target), capped to k_methods by caller-edge count; test/assert vertices restricted to
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
        # keep the RAW pre-focus classes_total (the field's "before any cap"
        # contract) rather than recomputing it from the failing-test-restricted set.
        g = MutationGraph(target_id=tgt, vertices=vs, edges=es,
                          classes_total=self.classes_total)
        return g.with_class_cap(class_cap)
