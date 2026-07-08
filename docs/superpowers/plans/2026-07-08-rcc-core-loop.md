# RapidCausalCoder Lite — Phase 1 (core loop) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The complete RCC causal-debugging loop as pure, injected-deps abench modules — subgraph builder, Alpha/Beta/Gamma prompts + parsing, subset suite runner with probe-log capture, memory store, and the LangGraph state machine — fully tested on fakes. NO runner/config wiring (that is Phase 2).

**Architecture:** Mirrors the parity-proven `orchestrator_graph.py` discipline: a `StateGraph` whose nodes call injected adapters (`phase_runner`, `suite_runner`, …), controller events with a monotone `clock`, and the same `stitch()` → `Trace` at the end. Every dependency is injected, so the whole graph is testable with fakes without opencode/gradle.

**Tech Stack:** Python 3.11+, LangGraph (existing optional extra `abench[langgraph]`), pytest.

Spec: `docs/superpowers/specs/2026-07-08-rapidcausalcoder-mvp-design.md`.

---

## File Structure

- Create: `abench/rcc_subgraph.py` — mutational subgraph from `.impact` artifacts (pure).
- Create: `abench/rcc_memory.py` — the Memory Graph JSON store (tolerant).
- Create: `abench/rcc_prompts.py` — Alpha/Beta/Gamma/fix prompt builders, Gamma JSON parsing, CausalRank.
- Modify: `abench/orchestration_adapters.py` — `subset_command`, `collect_probe_lines`, `make_subset_suite_runner` (appended at the end of the file).
- Create: `abench/rcc_graph.py` — `RccConfig`, `RccState`, `run_rcc(...)` (the LangGraph loop).
- Test: `tests/test_rcc_subgraph.py`, `tests/test_rcc_memory.py`, `tests/test_rcc_prompts.py`, `tests/test_rcc_adapters.py`, `tests/test_rcc_graph.py`.

Existing pieces you will call but MUST NOT modify: `abench/orchestrator.py` (`PhaseOutcome`, `SuiteEval`, `_cap`, `_fmt_cluster`, `_track_best`), `abench/failure_report.py` (`cluster_failures`, `select_clusters`), `abench/trace_stitch.py` (`stitch`), `abench/trace_model.py` (`Step`, `StepKind`, `Trace`), `abench/regression_gate.py` (`SuiteResult`), `abench/git_snapshot.py` (`strip_marked_lines` — used by Phase 2 wiring; here the strip is an injected callable), `abench/verify.py` (`_system_for_command`).

Reference data shapes (real artifacts, see `experiments/picocli-putValue/overlays/impact/.impact/`):
- `coverage.json` = `{method_fqn: [test_fqn, ...]}` — the joern-precomputed neighborhood around the experiment targets (~17 methods for picocli).
- `methods.json` = `{method_fqn: {"file": rel_path, "start": int, "end": int}}` — source spans anchored to the seed.

---

### Task 1: `rcc_subgraph.py` — the mutational subgraph

**Files:**
- Create: `abench/rcc_subgraph.py`
- Test: `tests/test_rcc_subgraph.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_rcc_subgraph.py
import json

from abench.rcc_subgraph import RccSubgraph, build_subgraph, find_target_fqn


def _write_impact(tmp_path, coverage, methods=None):
    d = tmp_path / ".impact"
    d.mkdir()
    (d / "coverage.json").write_text(json.dumps(coverage))
    (d / "methods.json").write_text(json.dumps(methods or {}))
    return d


_COV = {
    "p.C.putValue": ["p.T1.a", "p.T1.b", "p.T2.c"],
    "p.C.getValue": ["p.T1.a", "p.T2.c"],          # overlap 2
    "p.C.parse":    ["p.T1.a"],                     # overlap 1
    "p.C.far":      ["p.T3.z"],                     # overlap 0 -> excluded
}


def test_find_target_matches_method_name_like_blast_radius():
    assert find_target_fqn(_COV, ["putValue"]) == "p.C.putValue"
    assert find_target_fqn(_COV, ["nosuch"]) is None
    assert find_target_fqn({}, ["putValue"]) is None


def test_build_subgraph_ranks_by_test_overlap_and_excludes_zero(tmp_path):
    impact = _write_impact(tmp_path, _COV)
    sub = build_subgraph(impact, tmp_path, ["putValue"])
    assert sub.target_fqn == "p.C.putValue"
    assert sub.methods == ["p.C.putValue", "p.C.getValue", "p.C.parse"]
    assert sub.test_fqns == ["p.T1.a", "p.T1.b", "p.T2.c"]
    assert sub.test_classes == ["p.T1", "p.T2"]


def test_build_subgraph_k_caps_neighbors(tmp_path):
    impact = _write_impact(tmp_path, _COV)
    sub = build_subgraph(impact, tmp_path, ["putValue"], k=1)
    assert sub.methods == ["p.C.putValue", "p.C.getValue"]


def test_build_subgraph_none_when_no_coverage_or_no_target(tmp_path):
    assert build_subgraph(tmp_path / "missing", tmp_path, ["putValue"]) is None
    impact = _write_impact(tmp_path, _COV)
    assert build_subgraph(impact, tmp_path, ["nosuch"]) is None


def test_sources_read_span_with_margin_and_cap(tmp_path):
    src = tmp_path / "src" / "C.java"
    src.parent.mkdir(parents=True)
    src.write_text("\n".join(f"line{i}" for i in range(1, 101)))
    methods = {"p.C.putValue": {"file": "src/C.java", "start": 50, "end": 52}}
    impact = _write_impact(tmp_path, {"p.C.putValue": ["p.T1.a"]}, methods)
    sub = build_subgraph(impact, tmp_path, ["putValue"], margin=2, cap=10_000)
    text = sub.sources["p.C.putValue"]
    assert text.splitlines()[0] == "line48"          # start-1-margin (0-based 47)
    assert text.splitlines()[-1] == "line54"         # end+margin
    # missing file -> empty snippet, never a crash
    methods_bad = {"p.C.putValue": {"file": "nope.java", "start": 1, "end": 2}}
    impact2 = tmp_path / "i2"; impact2.mkdir()
    (impact2 / "coverage.json").write_text(json.dumps({"p.C.putValue": ["p.T1.a"]}))
    (impact2 / "methods.json").write_text(json.dumps(methods_bad))
    sub2 = build_subgraph(impact2, tmp_path, ["putValue"])
    assert sub2.sources["p.C.putValue"] == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_rcc_subgraph.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'abench.rcc_subgraph'`

- [ ] **Step 3: Implement `abench/rcc_subgraph.py`**

```python
"""Deterministic mutational subgraph for RapidCausalCoder (rcc).

Built from the impact artifacts: ``.impact/coverage.json`` ({method_fqn: [test
fqns]} — the joern-precomputed neighborhood around the experiment targets) and
``.impact/methods.json`` ({method_fqn: {file,start,end}} spans anchored to the
seed). The subgraph = the changed method + neighbors ranked by covering-test
overlap with it (top-K). This ranking IS the MVP filter node — the seam where
k-medoid / explicit call-graph-distance filters slot in later. Pure; no LLM.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RccSubgraph:
    target_fqn: str
    methods: list[str]                      # target first, then ranked neighbors
    test_fqns: list[str]                    # union of covering tests (sorted)
    test_classes: list[str]                 # distinct test-class FQNs (sorted)
    sources: dict[str, str] = field(default_factory=dict)   # method_fqn -> snippet


def _load(path: Path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def find_target_fqn(coverage: dict, target_methods: "list[str]") -> "str | None":
    """First coverage key whose method-name part (sans package/class$nesting) is
    in target_methods — the same matching rule as graph_cover.blast_radius_keys."""
    wanted = set(target_methods or [])
    for fqn in coverage or {}:
        if isinstance(fqn, str) and fqn.rsplit(".", 1)[-1].split("$")[-1] in wanted:
            return fqn
    return None


def read_span(workdir: Path, meta: dict, margin: int = 15, cap: int = 1200) -> str:
    """The method's source lines (per the methods.json span) ± margin, capped.
    Spans are anchored to the seed; agent edits may shift lines — the margin
    absorbs small drift, and a missing/renamed file degrades to ''. """
    try:
        text = (Path(workdir) / meta["file"]).read_text(encoding="utf-8",
                                                        errors="replace")
    except (OSError, KeyError, TypeError):
        return ""
    lines = text.splitlines()
    start = max(0, int(meta.get("start", 1)) - 1 - margin)
    end = min(len(lines), int(meta.get("end", start + 1)) + margin)
    return "\n".join(lines[start:end])[:cap]


def build_subgraph(impact_dir, workdir, target_methods, *, k: int = 5,
                   margin: int = 15, cap: int = 1200) -> "RccSubgraph | None":
    """None when coverage is absent/empty or no target matches — the caller
    (Phase 2 wiring) then degrades to plain phased, mirroring phased_graph."""
    impact_dir = Path(impact_dir)
    coverage = _load(impact_dir / "coverage.json")
    if not isinstance(coverage, dict) or not coverage:
        return None
    target = find_target_fqn(coverage, target_methods)
    if target is None:
        return None
    t_tests = set(coverage.get(target) or [])

    def overlap(fqn: str) -> int:
        return len(t_tests & set(coverage.get(fqn) or []))

    neighbors = sorted((f for f in coverage if f != target),
                       key=lambda f: (-overlap(f), f))
    methods = [target] + [f for f in neighbors if overlap(f) > 0][:k]
    tests = sorted({t for m in methods for t in (coverage.get(m) or [])})
    classes = sorted({t.rsplit(".", 1)[0] for t in tests})
    meta = _load(impact_dir / "methods.json") or {}
    sources = {m: read_span(workdir, meta[m], margin=margin, cap=cap)
               for m in methods if m in meta}
    return RccSubgraph(target_fqn=target, methods=methods, test_fqns=tests,
                       test_classes=classes, sources=sources)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_rcc_subgraph.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add abench/rcc_subgraph.py tests/test_rcc_subgraph.py
git commit -m "feat(rcc): mutational subgraph from impact artifacts (test-overlap ranking)"
```

---

### Task 2: `rcc_memory.py` — the Memory Graph store

**Files:**
- Create: `abench/rcc_memory.py`
- Test: `tests/test_rcc_memory.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_rcc_memory.py
from abench.rcc_memory import RccMemory


def test_roundtrip_and_persistence(tmp_path):
    p = tmp_path / "mem" / "rcc-memory.json"
    m = RccMemory(p)
    assert m.get("p.C.putValue") is None
    m.put("p.C.putValue", {"nodes": [], "edges": []}, ["p.T1"])
    e = m.get("p.C.putValue")
    assert e["causal_graph"] == {"nodes": [], "edges": []}
    assert e["test_classes"] == ["p.T1"]
    assert e["ts"] > 0
    # a fresh instance reads the same file
    assert RccMemory(p).get("p.C.putValue")["test_classes"] == ["p.T1"]


def test_invalidate_removes_and_persists(tmp_path):
    p = tmp_path / "m.json"
    m = RccMemory(p)
    m.put("a", {}, [])
    m.invalidate("a")
    assert m.get("a") is None
    assert RccMemory(p).get("a") is None
    m.invalidate("never-there")            # no-op, no crash


def test_corrupt_or_missing_file_is_empty(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    assert RccMemory(p).get("x") is None
    p2 = tmp_path / "list.json"
    p2.write_text("[1,2]")
    assert RccMemory(p2).get("x") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_rcc_memory.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'abench.rcc_memory'`

- [ ] **Step 3: Implement `abench/rcc_memory.py`**

```python
"""Memory Graph for rcc: a tolerant JSON store, ``fqn -> {causal_graph,
test_classes, ts}``. Exact-match keys (semantic lookup is a later phase). The
A/B runner gives each rep a FRESH file (rep independence); the hit-rate demo
passes one persistent path across two runs — both are Phase 2 wiring."""
from __future__ import annotations

import json
import time
from pathlib import Path


class RccMemory:
    def __init__(self, path):
        self.path = Path(path)
        self._data = self._load()

    def _load(self) -> dict:
        try:
            d = json.loads(self.path.read_text())
            if isinstance(d, dict) and isinstance(d.get("entries"), dict):
                return d
        except (OSError, ValueError):
            pass
        return {"entries": {}}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, indent=2))
        except OSError:
            pass                                    # best-effort persistence

    def get(self, fqn: str) -> "dict | None":
        return self._data["entries"].get(fqn)

    def put(self, fqn: str, causal_graph: dict, test_classes: list) -> None:
        self._data["entries"][fqn] = {"causal_graph": causal_graph,
                                      "test_classes": list(test_classes),
                                      "ts": time.time()}
        self._save()

    def invalidate(self, fqn: str) -> None:
        if self._data["entries"].pop(fqn, None) is not None:
            self._save()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_rcc_memory.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add abench/rcc_memory.py tests/test_rcc_memory.py
git commit -m "feat(rcc): Memory Graph JSON store (exact-match, tolerant)"
```

---

### Task 3: `rcc_prompts.py` — Alpha/Beta/Gamma + parsing + CausalRank

**Files:**
- Create: `abench/rcc_prompts.py`
- Test: `tests/test_rcc_prompts.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_rcc_prompts.py
import json

from abench.rcc_prompts import (
    GAMMA_FORMAT_REMINDER, PROBE_MARKER, PROBE_PREFIX, alpha_prompt, beta_prompt,
    beta_repair_prompt, cache_fix_prompt, causal_rank, fix_prompt, gamma_prompt,
    parse_gamma, root_rank,
)
from abench.rcc_subgraph import RccSubgraph

_SUB = RccSubgraph(
    target_fqn="p.C.putValue",
    methods=["p.C.putValue", "p.C.getValue"],
    test_fqns=["p.CT.t1"], test_classes=["p.CT"],
    sources={"p.C.putValue": "public Object putValue() { return null; }"},
)

_GRAPH = {
    "nodes": [{"id": "p.C.putValue", "type": "method"},
              {"id": "spec_put", "type": "spec", "method": "p.C.putValue"},
              {"id": "p.C.getValue", "type": "method"}],
    "edges": [
        {"src": "spec_put", "tgt": "p.C.getValue", "type": "causal", "weight": 0.9},
        {"src": "p.C.putValue", "tgt": "p.C.getValue", "type": "causal", "weight": 1.0},
        {"src": "p.C.putValue", "tgt": "p.C.getValue", "type": "calls", "weight": 1.0},
        {"src": "p.C.getValue", "tgt": "p.C.putValue", "type": "causal", "weight": "bad"},
    ],
}


def test_parse_gamma_accepts_json_embedded_in_prose():
    text = "Here is the graph:\n" + json.dumps(_GRAPH) + "\nDone."
    assert parse_gamma(text)["edges"][0]["weight"] == 0.9


def test_parse_gamma_rejects_garbage_and_wrong_shape():
    assert parse_gamma("no json at all") is None
    assert parse_gamma('{"nodes": "not-a-list", "edges": []}') is None
    assert parse_gamma("") is None
    assert parse_gamma(None) is None


def test_causal_rank_sums_causal_weights_via_node_method_attribution():
    ranks = causal_rank(_GRAPH, _SUB.methods)
    # putValue: 0.9 (spec node attributed to it) + 1.0 direct = 1.9
    # getValue: the malformed weight falls back to 0.5; 'calls' edges don't count
    assert ranks == [("p.C.putValue", 1.9), ("p.C.getValue", 0.5)]
    assert root_rank(ranks, "p.C.putValue") == 1
    assert root_rank(ranks, "p.C.nope") is None


def test_causal_rank_empty_graph_keeps_subgraph_order():
    ranks = causal_rank({"nodes": [], "edges": []}, _SUB.methods)
    assert ranks == [("p.C.putValue", 0.0), ("p.C.getValue", 0.0)]


def test_prompts_carry_the_contract_pieces():
    a = alpha_prompt(_SUB)
    assert "p.C.putValue" in a and "return null" in a and "pre" in a
    b = beta_prompt(_SUB, "SPECS-TEXT")
    assert PROBE_PREFIX in b and PROBE_MARKER in b and "SPECS-TEXT" in b
    assert PROBE_MARKER in beta_repair_prompt(_SUB)
    g = gamma_prompt(_SUB, "SPECS-TEXT", ["RCC_PROBE C.putValue: ret=null"])
    assert "ret=null" in g and '"causal"' in g and "p.C.getValue" in g
    g2 = gamma_prompt(_SUB, "S", [])
    assert "no runtime logs" in g2
    f = fix_prompt("the target", "p.C.putValue", _GRAPH, "SPECS", [],
                   "p.C.putValue", attempt=1)
    assert "root" in f.lower() and "CAUSAL GRAPH" in f
    f2 = fix_prompt("the target", "p.C.putValue", None, "SPECS", [],
                    "p.C.getValue", attempt=2)
    assert "did NOT go green" in f2 and "degraded" in f2
    c = cache_fix_prompt("the target", _GRAPH, [])
    assert "previous successful" in c
    assert "JSON" in GAMMA_FORMAT_REMINDER
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_rcc_prompts.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'abench.rcc_prompts'`

- [ ] **Step 3: Implement `abench/rcc_prompts.py`**

```python
"""RapidCausalCoder prompt builders (Alpha/Beta/Gamma/fix) + Gamma JSON parsing
+ CausalRank. Pure text/data functions — no I/O, no LLM calls (the graph node
calls phase_runner with these strings)."""
from __future__ import annotations

import json

from .orchestrator import _cap, _fmt_cluster
from .rcc_subgraph import RccSubgraph

PROBE_MARKER = "//[probe]"
PROBE_PREFIX = "RCC_PROBE"
_MAX_SPECS_CHARS = 4000
_MAX_GRAPH_CHARS = 4000
_MAX_LOG_LINES = 200

GAMMA_FORMAT_REMINDER = (
    "\n\nREMINDER: your previous answer was not parseable. Return ONLY the JSON "
    "object described above — no prose, no markdown fences.")


def _methods_block(sub: RccSubgraph) -> str:
    parts = []
    for m in sub.methods:
        src = sub.sources.get(m, "")
        parts.append(f"### {m}\n```java\n{src}\n```" if src
                     else f"### {m} (source unavailable — read it yourself)")
    return "\n".join(parts)


def alpha_prompt(sub: RccSubgraph) -> str:
    return (
        "You are writing behavioural CONTRACTS (textual specifications) for the "
        f"methods around {sub.target_fqn}.\n"
        "For EACH method below write:\n"
        "- pre: preconditions (inputs/state it may assume)\n"
        "- post: postconditions (what it guarantees: return value, state changes)\n"
        "- inv: invariants that must hold throughout\n"
        "Base them on the source shown and anything you read. Do NOT edit code.\n\n"
        "METHODS:\n" + _methods_block(sub))


def beta_prompt(sub: RccSubgraph, specs_text: str) -> str:
    return (
        "Instrument the code for INVASIVE DEBUGGING so we can check the contracts "
        "against actual runtime values.\n"
        "Insert System.out.println lines into the methods below. EVERY inserted "
        "line must:\n"
        f"- print a message starting with \"{PROBE_PREFIX} <Class.method>: \" with the "
        "variables that matter (arguments at entry, return value at exit, key "
        "branch state);\n"
        f"- end with the trailing comment {PROBE_MARKER} on the SAME line (these "
        "lines are mechanically stripped later);\n"
        "- change NO behaviour: no logic edits, no new fields, keep the code "
        "compiling.\n\n"
        "CONTRACTS to check:\n" + _cap(specs_text, _MAX_SPECS_CHARS) + "\n\n"
        "METHODS:\n" + _methods_block(sub))


def beta_repair_prompt(sub: RccSubgraph) -> str:
    return (
        "The instrumented build no longer compiles. Fix the compilation WITHOUT "
        f"removing your {PROBE_PREFIX} println lines if possible — but compiling "
        "matters most: delete a probe line rather than leave the build broken. "
        f"Every probe line keeps its trailing {PROBE_MARKER} comment on the same "
        "line. Do not change any program logic.")


def gamma_prompt(sub: RccSubgraph, specs_text: str, probe_lines: list) -> str:
    logs = "\n".join((probe_lines or [])[:_MAX_LOG_LINES]) \
        or "(no runtime logs — instrumentation was skipped)"
    methods = "\n".join(f"- {m}" for m in sub.methods)
    return (
        "Build a CAUSAL GRAPH (CausalDeltaSubGraph) explaining the failing "
        "tests. Inputs: the method subgraph, their contracts, and runtime probe "
        "logs.\n"
        "For each contract violation find its CAUSE in the logs (a violated "
        "invariant, or bad input coming from an upstream method) and add a "
        "directed 'causal' edge — weight 1.0 for a direct violation, 0.5 for an "
        "indirect one — with a short 'reason'.\n"
        'Return ONLY a JSON object: {"nodes": [{"id": <method fqn or spec id>, '
        '"type": "method"|"spec", "method": <owning method fqn>}], '
        '"edges": [{"src": <id>, "tgt": <id>, "type": "calls"|"data_dep"|"causal", '
        '"weight": <0..1>, "reason": <str>}]}.\n'
        "Node ids for methods MUST be exactly these FQNs:\n" + methods + "\n\n"
        "CONTRACTS:\n" + _cap(specs_text, _MAX_SPECS_CHARS)
        + "\n\nPROBE LOGS:\n" + logs)


def fix_prompt(target_label: str, target_fqn: str, graph: "dict | None",
               specs_text: str, clusters: list, focus_fqn: str,
               attempt: int) -> str:
    gtxt = (_cap(json.dumps(graph, indent=1), _MAX_GRAPH_CHARS) if graph
            else "(no causal graph — analysis degraded; rely on the failures and "
                 "contracts)")
    body = "\n".join(_fmt_cluster(c) for c in clusters) \
        or "(no parsed failure clusters)"
    focus = (f"The causal analysis points at {focus_fqn} as the root."
             if focus_fqn == target_fqn else
             f"The causal analysis points at {focus_fqn}; trace how it breaks "
             f"{target_fqn}.")
    retry = ("" if attempt == 1 else
             "\nYour previous fix attempt did NOT go green — take a different "
             "angle on the root cause.")
    return (f"Fix the ROOT CAUSE of the failing tests with ONE change to "
            f"{target_label}.{retry}\n{focus}\n\nCAUSAL GRAPH:\n{gtxt}\n\n"
            f"FAILURE CLUSTERS:\n{body}\n\nCONTRACTS (for reference):\n"
            + _cap(specs_text, _MAX_SPECS_CHARS))


def cache_fix_prompt(target_label: str, graph: dict, clusters: list) -> str:
    body = "\n".join(_fmt_cluster(c) for c in clusters) \
        or "(no parsed failure clusters)"
    return (f"A previous successful debugging session of {target_label} produced "
            "this causal graph of how it breaks. Apply the SAME root-cause fix "
            "to the current code.\n\nCAUSAL GRAPH (cached):\n"
            + _cap(json.dumps(graph, indent=1), _MAX_GRAPH_CHARS)
            + "\n\nCURRENT FAILURES:\n" + body)


def parse_gamma(text: "str | None") -> "dict | None":
    """First parseable JSON object in the text with list-typed nodes+edges —
    tolerant of prose/fences around it. None otherwise."""
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
        if (isinstance(obj, dict) and isinstance(obj.get("nodes"), list)
                and isinstance(obj.get("edges"), list)):
            return obj
    return None


def _edge_weight(e: dict) -> float:
    try:
        return float(e.get("weight", 0.5))
    except (TypeError, ValueError):
        return 0.5


def _match_method(name: "str | None", methods: list) -> "str | None":
    """Map a node id / method attribute onto a subgraph method: exact FQN, else
    a UNIQUE simple-name match (Gamma is told to use exact FQNs; this absorbs
    the common slip of using the bare method name)."""
    if not name:
        return None
    if name in methods:
        return name
    tail = str(name).split("(")[0].rsplit(".", 1)[-1].split("$")[-1]
    hits = [m for m in methods if m.rsplit(".", 1)[-1].split("$")[-1] == tail]
    return hits[0] if len(hits) == 1 else None


def causal_rank(graph: dict, methods: list) -> "list[tuple[str, float]]":
    """CausalRank(m) = Σ weight of 'causal' edges whose SOURCE attributes to m
    (spec nodes attribute to their 'method'). Sorted desc; ties keep subgraph
    order (target first) — which is also the degraded no-graph ranking."""
    node_method: dict = {}
    for n in graph.get("nodes", []) or []:
        if isinstance(n, dict) and n.get("id") is not None:
            owner = _match_method(n.get("method") or n.get("id"), methods)
            if owner:
                node_method[str(n["id"])] = owner
    score = {m: 0.0 for m in methods}
    for e in graph.get("edges", []) or []:
        if not isinstance(e, dict) or e.get("type") != "causal":
            continue
        src = str(e.get("src") or e.get("source") or "")
        m = node_method.get(src) or _match_method(src, methods)
        if m:
            score[m] += _edge_weight(e)
    order = {m: i for i, m in enumerate(methods)}
    return sorted(score.items(), key=lambda kv: (-kv[1], order[kv[0]]))


def root_rank(ranks: list, target_fqn: str) -> "int | None":
    for i, (m, _w) in enumerate(ranks, 1):
        if m == target_fqn:
            return i
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_rcc_prompts.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add abench/rcc_prompts.py tests/test_rcc_prompts.py
git commit -m "feat(rcc): Alpha/Beta/Gamma prompts, gamma JSON parsing, CausalRank"
```

---

### Task 4: subset suite runner + probe-line capture (adapters)

**Files:**
- Modify: `abench/orchestration_adapters.py` (append at end of file)
- Test: `tests/test_rcc_adapters.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_rcc_adapters.py
from abench.orchestration_adapters import collect_probe_lines, subset_command


def test_subset_command_gradle_appends_class_filters():
    cmd = subset_command("gradle test --continue", ["p.CT", "p.OtherTest"])
    assert cmd == 'gradle test --continue --tests "p.CT" --tests "p.OtherTest"'


def test_subset_command_maven_uses_dtest():
    cmd = subset_command("mvn -q test", ["p.CT", "p.DT"])
    assert "-Dtest=p.CT,p.DT" in cmd and "-DfailIfNoTests=false" in cmd


def test_subset_command_unknown_or_empty_returns_base():
    assert subset_command("make check", ["p.CT"]) == "make check"
    assert subset_command("gradle test", []) == "gradle test"


def test_collect_probe_lines_from_stdout_and_junit_xml(tmp_path):
    xml_dir = tmp_path / "build" / "test-results" / "test"
    xml_dir.mkdir(parents=True)
    (xml_dir / "TEST-p.CT.xml").write_text(
        '<testsuite name="p.CT" tests="1" failures="0">'
        "<system-out>noise\nRCC_PROBE C.putValue: ret=null\n</system-out>"
        "</testsuite>")
    out = "gradle noise\nRCC_PROBE C.getValue: ret=null\nRCC_PROBE C.putValue: ret=null\n"
    lines = collect_probe_lines(tmp_path, out)
    # deduped, order: stdout scanned first, then the XML
    assert lines == ["RCC_PROBE C.getValue: ret=null",
                     "RCC_PROBE C.putValue: ret=null"]


def test_collect_probe_lines_caps(tmp_path):
    out = "\n".join(f"RCC_PROBE m: v={i}" for i in range(500))
    assert len(collect_probe_lines(tmp_path, out, max_lines=300)) == 300
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_rcc_adapters.py -q`
Expected: FAIL — `ImportError: cannot import name 'collect_probe_lines'`

- [ ] **Step 3: Append to `abench/orchestration_adapters.py`**

Add at the END of the file (after `build_orchestrator_config`):

```python
# ── RapidCausalCoder (rcc) additions ─────────────────────────────────────────

def subset_command(base_command: str, test_classes: "list[str]") -> str:
    """Narrow the suite command to the given test CLASSES (class-level, not
    method-level — method filters are flaky with parameterized tests).
    Gradle: repeated --tests (with --continue already on the base command,
    modules where a pattern matches nothing fail that task but the matched
    modules still run — and only JUnit XML feeds the counts). Maven: -Dtest=…
    with -DfailIfNoTests=false. Unknown build system → base command unchanged
    (falls back to the full suite; slower but correct)."""
    from .verify import _system_for_command
    if not test_classes:
        return base_command
    system = _system_for_command(base_command)
    if system == "gradle":
        pats = " ".join(f'--tests "{c}"' for c in test_classes)
        return f"{base_command} {pats}"
    if system == "maven":
        return (f"{base_command} -Dtest={','.join(test_classes)} "
                "-DfailIfNoTests=false")
    return base_command


def collect_probe_lines(workdir, out_text: str, prefix: str = "RCC_PROBE",
                        max_lines: int = 300) -> "list[str]":
    """Probe println lines from a test run: the subprocess output PLUS every
    JUnit XML <system-out> (gradle hides test stdout from the console but
    records it in the XML). Deduped, order-preserving, capped."""
    seen: set = set()
    lines: list = []

    def scan(text: "str | None") -> None:
        for ln in (text or "").splitlines():
            ln = ln.strip()
            if prefix in ln and ln not in seen:
                seen.add(ln)
                lines.append(ln)

    scan(out_text)
    for xml in Path(workdir).rglob("TEST-*.xml"):
        try:
            root = ET.fromstring(xml.read_text())
        except (OSError, ET.ParseError):
            continue
        for so in root.iter("system-out"):
            scan(so.text)
    return lines[:max_lines]


def make_subset_suite_runner(workdir, base_command: str, timeout_s: int):
    """Like make_suite_runner, but narrowed per call to the given test classes
    and ALSO returning that run's probe lines:
    ``Callable[[list[str]], tuple[SuiteEval, list[str]]]``."""
    workdir = Path(workdir)

    def runner(test_classes: "list[str]") -> "tuple[SuiteEval, list[str]]":
        _clear_results(workdir)
        cmd = subset_command(base_command, test_classes)
        try:
            proc = subprocess.run(cmd, shell=True, cwd=workdir,
                                  capture_output=True, text=True,
                                  timeout=timeout_s, env=dict(os.environ))
            out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        except (subprocess.TimeoutExpired, OSError):
            return (SuiteEval(result=SuiteResult(compiled=True, ran=False,
                                                 executed=0, passed=0,
                                                 failed=0)), [])
        ev = eval_from_junit(workdir, compiled=True, ran=True)
        compiled, ran = build_status(out, ev.result.executed)
        ev.result.compiled = compiled
        ev.result.ran = ran
        return ev, collect_probe_lines(workdir, out)

    return runner
```

(`Path`, `ET`, `os`, `subprocess`, `SuiteEval`, `SuiteResult`, `eval_from_junit`, `build_status`, `_clear_results` are already imported/defined at the top of this module — do not re-import.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_rcc_adapters.py -q`
Expected: 5 passed

- [ ] **Step 5: Run the module's existing tests (no regressions)**

Run: `python3 -m pytest tests/test_orchestration_adapters.py -q 2>/dev/null || python3 -m pytest tests/ -q -k "adapter"`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add abench/orchestration_adapters.py tests/test_rcc_adapters.py
git commit -m "feat(rcc): subset suite runner + probe-line capture (console + junit system-out)"
```

---

### Task 5: `rcc_graph.py` — the LangGraph loop (happy paths)

**Files:**
- Create: `abench/rcc_graph.py`
- Test: `tests/test_rcc_graph.py`

- [ ] **Step 1: Write the failing tests (happy paths)**

```python
# tests/test_rcc_graph.py
import json

import pytest

pytest.importorskip("langgraph")   # optional extra — skip cleanly without it

from abench.orchestrator import PhaseOutcome, SuiteEval
from abench.rcc_graph import RccConfig, run_rcc
from abench.rcc_subgraph import RccSubgraph
from abench.regression_gate import SuiteResult
from abench.trace_model import StepKind, Trace

_SUB = RccSubgraph(
    target_fqn="p.C.put", methods=["p.C.put", "p.C.get"],
    test_fqns=["p.CT.t1", "p.CT.t2"], test_classes=["p.CT"],
    sources={"p.C.put": "Object put() { return null; }"},
)

_GAMMA = json.dumps({
    "nodes": [{"id": "p.C.put", "type": "method"},
              {"id": "p.C.get", "type": "method"}],
    "edges": [{"src": "p.C.put", "tgt": "p.C.get", "type": "causal",
               "weight": 0.9, "reason": "put returns null -> get NPE"}],
})


def _ev(passed, failed, compiled=True, ran=True):
    return SuiteEval(result=SuiteResult(compiled=compiled, ran=ran,
                                        executed=passed + failed,
                                        passed=passed, failed=failed))


class FakePhase:
    """phase_runner fake: records calls; canned text per phase kind."""
    def __init__(self, gamma_texts=(_GAMMA,), alpha_text="specs: put returns non-null"):
        self.calls = []
        self.gamma_texts = list(gamma_texts)
        self.alpha_text = alpha_text

    def __call__(self, phase, prompt, tools):
        self.calls.append((phase, prompt, tuple(tools)))
        text = ""
        if phase == "alpha":
            text = self.alpha_text
        elif phase.startswith("gamma"):
            text = self.gamma_texts.pop(0) if self.gamma_texts else ""
        return PhaseOutcome(trace=Trace(), text=text)


def _seq_subset(evals_and_lines):
    it = iter(evals_and_lines)

    def run(test_classes):
        return next(it)
    return run


def _seq_full(evals):
    it = iter(evals)

    def run():
        return next(it)
    return run


class FakeMemory:
    def __init__(self, entries=None):
        self.entries = dict(entries or {})
        self.puts, self.invalidations = [], []

    def get(self, fqn):
        return self.entries.get(fqn)

    def put(self, fqn, causal_graph, test_classes):
        self.puts.append(fqn)
        self.entries[fqn] = {"causal_graph": causal_graph,
                             "test_classes": list(test_classes), "ts": 1.0}

    def invalidate(self, fqn):
        self.invalidations.append(fqn)
        self.entries.pop(fqn, None)


def _events(trace):
    return [s.text for s in trace.steps if s.kind == StepKind.CONTROLLER]


def _phases_called(fake):
    return [c[0] for c in fake.calls]


def _run(phase, subset_seq, full_seq, memory=None, cfg=None, strip=None):
    strips = []
    tr = run_rcc(
        cfg or RccConfig(target_label="p.C.put"), _SUB, initial=_ev(0, 2),
        phase_runner=phase,
        suite_runner=_seq_full(full_seq),
        subset_runner=_seq_subset(subset_seq),
        memory=memory if memory is not None else FakeMemory(),
        strip_probes=strip or (lambda: strips.append(1) or 3),
    )
    return tr, strips


def test_green_on_top1():
    phase = FakePhase()
    # subset calls: beta probe run (red, with logs), fix-1 subset (green)
    subset = [(_ev(1, 1), ["RCC_PROBE C.put: ret=null"]), (_ev(2, 0), [])]
    full = [_ev(100, 0)]                       # fix-1 full suite
    mem = FakeMemory()
    tr, strips = _run(phase, subset, full, memory=mem)
    assert tr.orchestration_outcome == "green"
    assert _phases_called(phase) == ["alpha", "beta", "gamma", "fix-1"]
    assert mem.puts == ["p.C.put"]
    assert strips == [1]                       # probes stripped exactly once
    ev = "\n".join(_events(tr))
    assert "CausalRank of target = 1/2" in ev
    assert "memory: miss" in ev


def test_top2_rescue():
    phase = FakePhase()
    subset = [(_ev(1, 1), ["RCC_PROBE x"]),    # beta probe run
              (_ev(1, 1), []),                 # fix-1 subset red
              (_ev(2, 0), [])]                 # fix-2 subset green
    full = [_ev(100, 0)]                       # fix-2 full
    tr, _ = _run(phase, subset, full)
    assert tr.orchestration_outcome == "green"
    assert _phases_called(phase) == ["alpha", "beta", "gamma", "fix-1", "fix-2"]


def test_defer_after_max_attempts():
    phase = FakePhase()
    subset = [(_ev(1, 1), []), (_ev(1, 1), []), (_ev(1, 1), [])]
    full = []                                  # full suite never reached
    mem = FakeMemory()
    tr, _ = _run(phase, subset, full, memory=mem)
    assert tr.orchestration_outcome == "stuck"
    assert mem.puts == []                      # nothing saved on DEFER
    assert "finalized: stuck" in "\n".join(_events(tr))


def test_full_suite_red_consumes_attempt():
    phase = FakePhase()
    subset = [(_ev(1, 1), []),                 # beta
              (_ev(2, 0), []),                 # fix-1 subset green
              (_ev(2, 0), [])]                 # fix-2 subset green
    full = [_ev(90, 10), _ev(100, 0)]          # fix-1 full red -> fix-2 full green
    tr, _ = _run(phase, subset, full)
    assert tr.orchestration_outcome == "green"
    assert _phases_called(phase)[-2:] == ["fix-1", "fix-2"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_rcc_graph.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'abench.rcc_graph'`

- [ ] **Step 3: Implement `abench/rcc_graph.py`**

```python
"""RapidCausalCoder Lite (rcc) — a LangGraph causal-debugging loop.

Single pass: memory check → [cached fast fix] → Alpha (specs) → Beta
(//[probe] println instrumentation + instrumented subset run) → strip probes →
Gamma (causal graph JSON) → CausalRank → fix top-1 → subset → full suite →
fix top-2 → DEFER. Same event/clock/stitch discipline as orchestrator_graph
(the parity-proven pattern); every dependency injected, so the whole loop runs
on fakes. Spec: docs/superpowers/specs/2026-07-08-rapidcausalcoder-mvp-design.md
"""
from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import Annotated, TypedDict

from .failure_report import cluster_failures, select_clusters
from .orchestrator import PhaseOutcome, SuiteEval, _track_best
from .rcc_prompts import (
    GAMMA_FORMAT_REMINDER, alpha_prompt, beta_prompt, beta_repair_prompt,
    cache_fix_prompt, causal_rank, fix_prompt, gamma_prompt, parse_gamma,
    root_rank,
)
from .rcc_subgraph import RccSubgraph
from .regression_gate import SuiteResult
from .trace_model import Step, StepKind, Trace
from .trace_stitch import stitch


@dataclass
class RccConfig:
    target_label: str = "the target method"
    max_attempts: int = 2          # top-1 → top-2 → DEFER
    cluster_cap: int = 5


class RccState(TypedDict, total=False):
    cached: object                 # dict | None — memory entry (fast path)
    specs: str
    probe_lines: list
    beta_ok: bool
    graph: object                  # dict | None — parsed Gamma output
    ranks: list                    # [(method_fqn, score)] desc
    attempt: int
    cur: SuiteEval                 # latest CLEAN suite state (never instrumented)
    best_failed: object
    outcome: object
    phase_traces: Annotated[list, operator.add]
    ctrl: Annotated[list, operator.add]


def run_rcc(cfg: RccConfig, sub: RccSubgraph, initial: SuiteEval, *,
            phase_runner, suite_runner, subset_runner, memory, strip_probes,
            on_event=None, cancel_event=None) -> Trace:
    """The rcc loop. `initial` is the RED suite state that triggered rcc (the
    lead diff's failures). `subset_runner(classes) -> (SuiteEval, probe_lines)`;
    `suite_runner() -> SuiteEval` (full); `strip_probes() -> int` removes
    //[probe] lines from the working tree; `memory` is an RccMemory-like."""
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("orchestration=rcc requires the optional dep: "
                           "pip install -e '.[langgraph]'") from exc

    clock = [0.0]
    test_runs = [0]
    productive = [0]

    def emit(payload: dict) -> None:
        if on_event is not None:
            try:
                on_event(payload)
            except Exception:
                pass

    def event(text: str, phase: str) -> Step:
        clock[0] += 1.0
        emit({"type": "controller", "phase": phase, "text": text})
        return Step(kind=StepKind.CONTROLLER, ts=clock[0], turn=0, text=text,
                    phase=phase)

    def cancelled() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    def do_phase(name: str, prompt: str, tools: list, steps: list) -> PhaseOutcome:
        if cancelled():
            steps.append(event(f"run cancelled — skipping {name}", name))
            return PhaseOutcome(trace=Trace(), text="")
        emit({"type": "phase.start", "phase": name})
        emit({"type": "phase.prompt", "phase": name, "text": prompt})
        try:
            return phase_runner(name, prompt, tools)
        except Exception as exc:
            steps.append(event(f"phase {name} FAILED ({exc}); continuing degraded",
                               name))
            return PhaseOutcome(trace=Trace(), text="")

    def _norun() -> SuiteEval:
        return SuiteEval(result=SuiteResult(compiled=True, ran=False, executed=0,
                                            passed=0, failed=0))

    def run_full(steps: list, phase: str) -> SuiteEval:
        test_runs[0] += 1
        try:
            return suite_runner()
        except Exception as exc:
            steps.append(event(f"suite run FAILED ({exc})", phase))
            return _norun()

    def run_subset(steps: list, phase: str, classes: list):
        test_runs[0] += 1
        try:
            return subset_runner(classes)
        except Exception as exc:
            steps.append(event(f"subset run FAILED ({exc})", phase))
            return _norun(), []

    def safe_strip(steps: list, phase: str) -> int:
        try:
            return strip_probes()
        except Exception as exc:
            steps.append(event(f"probe strip FAILED ({exc})", phase))
            return 0

    def _green(ev: SuiteEval) -> bool:
        return ev.result.compiled and ev.result.ran and ev.result.failed == 0

    def clusters_of(ev: SuiteEval) -> list:
        return select_clusters(cluster_failures(ev.failures), cfg.cluster_cap)

    # ── nodes ────────────────────────────────────────────────────────────────
    def memory_node(state):
        steps: list = []
        entry = memory.get(sub.target_fqn)
        steps.append(event(
            f"memory: HIT for {sub.target_fqn} — trying the cached causal insight"
            if entry else
            f"memory: miss for {sub.target_fqn} — full causal pass", "memory"))
        return {"cached": entry, "attempt": 0, "cur": initial,
                "best_failed": initial.result.failed if initial.result.ran else None,
                "specs": "", "probe_lines": [], "graph": None,
                "ranks": [(m, 0.0) for m in sub.methods], "ctrl": steps}

    def cache_fix_node(state):
        steps: list = []
        f = do_phase("cache-fix",
                     cache_fix_prompt(cfg.target_label,
                                      state["cached"]["causal_graph"],
                                      clusters_of(state["cur"])),
                     ["read", "edit"], steps)
        classes = state["cached"].get("test_classes") or sub.test_classes
        ev, _lines = run_subset(steps, "cache-fix", classes)
        cur = ev
        if _green(ev):
            cur = run_full(steps, "cache-fix")
        if _green(cur):
            steps.append(event("cache-fix: cached insight fixed it — subset + "
                               "full suite green", "cache-fix"))
        else:
            memory.invalidate(sub.target_fqn)
            steps.append(event("cache-fix: cached insight is STALE (tests still "
                               "red) — invalidated; full causal pass", "cache-fix"))
        bf = _track_best(cur, state["best_failed"], productive)
        return {"cur": cur, "best_failed": bf,
                "phase_traces": [("cache-fix", f.trace)], "ctrl": steps}

    def alpha_node(state):
        steps: list = []
        a = do_phase("alpha", alpha_prompt(sub), ["read"], steps)
        specs = (a.text or "").strip()
        steps.append(event(
            f"alpha: contracts for {len(sub.methods)} methods ({len(specs)} chars)"
            if specs else "alpha: EMPTY contracts — continuing without", "alpha"))
        return {"specs": specs, "phase_traces": [("alpha", a.trace)],
                "ctrl": steps}

    def beta_node(state):
        steps: list = []
        traces: list = []
        b = do_phase("beta", beta_prompt(sub, state["specs"]), ["read", "edit"],
                     steps)
        traces.append(("beta", b.trace))
        ev, lines = run_subset(steps, "beta", sub.test_classes)
        beta_ok = ev.result.compiled and ev.result.ran
        if not beta_ok and not cancelled():
            steps.append(event("beta: instrumented build broke — one repair "
                               "attempt", "beta"))
            r = do_phase("beta-repair", beta_repair_prompt(sub), ["read", "edit"],
                         steps)
            traces.append(("beta-repair", r.trace))
            ev, lines = run_subset(steps, "beta", sub.test_classes)
            beta_ok = ev.result.compiled and ev.result.ran
        removed = safe_strip(steps, "beta")
        if beta_ok:
            steps.append(event(
                f"beta: probes ran — {len(lines)} probe lines from the subset "
                f"({ev.result.passed} passed / {ev.result.failed} failed, "
                f"instrumented); {removed} probe lines stripped", "beta"))
        else:
            lines = []
            steps.append(event(
                "beta: instrumentation failed twice — degrading to a NO-LOGS "
                f"causal pass; {removed} probe lines stripped", "beta"))
        return {"probe_lines": lines, "beta_ok": beta_ok,
                "phase_traces": traces, "ctrl": steps}

    def gamma_node(state):
        steps: list = []
        traces: list = []
        prompt = gamma_prompt(sub, state["specs"], state["probe_lines"])
        g1 = do_phase("gamma", prompt, ["read"], steps)
        traces.append(("gamma", g1.trace))
        graph = parse_gamma(g1.text)
        if graph is None and not cancelled():
            steps.append(event("gamma: unparseable causal graph — one "
                               "format-reminded retry", "gamma"))
            g2 = do_phase("gamma-retry", prompt + GAMMA_FORMAT_REMINDER,
                          ["read"], steps)
            traces.append(("gamma-retry", g2.trace))
            graph = parse_gamma(g2.text)
        if graph is None:
            ranks = [(m, 0.0) for m in sub.methods]
            steps.append(event("gamma: still unparseable — degraded to "
                               "subgraph-order ranking (target first)", "gamma"))
        else:
            ranks = causal_rank(graph, sub.methods)
            rr = root_rank(ranks, sub.target_fqn)
            steps.append(event(
                f"gamma: causal graph with {len(graph.get('nodes', []))} nodes / "
                f"{len(graph.get('edges', []))} edges; CausalRank of target = "
                f"{rr}/{len(ranks)}", "gamma"))
        return {"graph": graph, "ranks": ranks, "phase_traces": traces,
                "ctrl": steps}

    def fix_node(state):
        steps: list = []
        attempt = state["attempt"] + 1
        ranks = state["ranks"]
        focus = ranks[min(attempt - 1, len(ranks) - 1)][0]
        f = do_phase(f"fix-{attempt}",
                     fix_prompt(cfg.target_label, sub.target_fqn, state["graph"],
                                state["specs"], clusters_of(state["cur"]),
                                focus, attempt),
                     ["read", "edit"], steps)
        ev, _lines = run_subset(steps, f"fix-{attempt}", sub.test_classes)
        cur = ev
        if _green(ev):
            steps.append(event(f"fix {attempt} (focus {focus}): subset GREEN — "
                               "running the full suite", f"fix-{attempt}"))
            cur = run_full(steps, f"fix-{attempt}")
            steps.append(event(
                f"fix {attempt}: full suite {cur.result.passed} passed / "
                f"{cur.result.failed} failed (compiled={cur.result.compiled})",
                f"fix-{attempt}"))
        else:
            steps.append(event(
                f"fix {attempt} (focus {focus}): subset still red — "
                f"{ev.result.passed} passed / {ev.result.failed} failed",
                f"fix-{attempt}"))
        bf = _track_best(cur, state["best_failed"], productive)
        return {"attempt": attempt, "cur": cur, "best_failed": bf,
                "phase_traces": [(f"fix-{attempt}", f.trace)], "ctrl": steps}

    def finalize_node(state):
        cur = state["cur"]
        if cancelled():
            outcome = "cancelled"
        elif _green(cur):
            outcome = "green"
        elif not cur.result.compiled:
            outcome = "compile-fail"
        else:
            outcome = "stuck"
        graph_to_save = state.get("graph") \
            or (state.get("cached") or {}).get("causal_graph")
        saved = ""
        if outcome == "green" and graph_to_save:
            memory.put(sub.target_fqn, graph_to_save, sub.test_classes)
            saved = " — causal insight saved to memory"
        step = event(f"finalized: {outcome}{saved}: "
                     f"{cur.result.passed} passed / {cur.result.failed} failed "
                     f"(best reached: {state['best_failed']} failed)", "finalize")
        return {"outcome": outcome, "ctrl": [step]}

    # ── edges ────────────────────────────────────────────────────────────────
    def after_memory(state):
        return "cache_fix" if state["cached"] else "alpha"

    def after_cache(state):
        return "finalize" if (_green(state["cur"]) or cancelled()) else "alpha"

    def after_fix(state):
        if _green(state["cur"]) or cancelled() \
                or state["attempt"] >= cfg.max_attempts:
            return "finalize"
        return "fix"

    g = StateGraph(RccState)
    g.add_node("memory", memory_node)
    g.add_node("cache_fix", cache_fix_node)
    g.add_node("alpha", alpha_node)
    g.add_node("beta", beta_node)
    g.add_node("gamma", gamma_node)
    g.add_node("fix", fix_node)
    g.add_node("finalize", finalize_node)
    g.add_edge(START, "memory")
    g.add_conditional_edges("memory", after_memory,
                            {"cache_fix": "cache_fix", "alpha": "alpha"})
    g.add_conditional_edges("cache_fix", after_cache,
                            {"finalize": "finalize", "alpha": "alpha"})
    g.add_edge("alpha", "beta")
    g.add_edge("beta", "gamma")
    g.add_edge("gamma", "fix")
    g.add_conditional_edges("fix", after_fix,
                            {"fix": "fix", "finalize": "finalize"})
    g.add_edge("finalize", END)
    app = g.compile()

    final = app.invoke({}, config={"recursion_limit": cfg.max_attempts * 2 + 20})

    try:
        return stitch(final.get("phase_traces", []), final.get("ctrl", []),
                      outcome=final.get("outcome"),
                      controller_test_runs=test_runs[0],
                      accepted_rounds=productive[0], reverted_rounds=0,
                      best_failed_reached=final.get("best_failed"))
    except Exception as exc:  # pragma: no cover
        emit({"type": "controller", "phase": "finalize",
              "text": f"stitch FAILED ({exc})"})
        tr = Trace(steps=list(final.get("ctrl", [])), finished=True)
        tr.orchestration_outcome = final.get("outcome")
        tr.controller_test_runs = test_runs[0]
        tr.accepted_rounds = productive[0]
        tr.reverted_rounds = 0
        tr.best_failed_reached = final.get("best_failed")
        return tr
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_rcc_graph.py -q`
Expected: 4 passed (or skipped entirely if langgraph isn't installed — install with `pip install -e '.[langgraph]'` first)

- [ ] **Step 5: Commit**

```bash
git add abench/rcc_graph.py tests/test_rcc_graph.py
git commit -m "feat(rcc): the LangGraph causal-debugging loop (memory -> alpha/beta/gamma -> fix ladder)"
```

---

### Task 6: degrade + memory scenarios for the graph

**Files:**
- Modify: `tests/test_rcc_graph.py` (append)

- [ ] **Step 1: Write the failing tests (append to `tests/test_rcc_graph.py`)**

```python
def test_memory_hit_fast_path_skips_analysis():
    mem = FakeMemory({"p.C.put": {"causal_graph": json.loads(_GAMMA),
                                  "test_classes": ["p.CT"], "ts": 1.0}})
    phase = FakePhase()
    subset = [(_ev(2, 0), [])]                 # cache-fix subset green
    full = [_ev(100, 0)]                       # cache-fix full green
    tr, _ = _run(phase, subset, full, memory=mem)
    assert tr.orchestration_outcome == "green"
    assert _phases_called(phase) == ["cache-fix"]        # NO alpha/beta/gamma
    assert mem.invalidations == []
    assert "memory: HIT" in "\n".join(_events(tr))
    # the graph is (re)saved on success
    assert mem.puts == ["p.C.put"]


def test_stale_cache_invalidates_then_full_pass_succeeds():
    mem = FakeMemory({"p.C.put": {"causal_graph": json.loads(_GAMMA),
                                  "test_classes": ["p.CT"], "ts": 1.0}})
    phase = FakePhase()
    subset = [(_ev(1, 1), []),                 # cache-fix subset red -> stale
              (_ev(1, 1), ["RCC_PROBE x"]),    # beta probe run
              (_ev(2, 0), [])]                 # fix-1 subset green
    full = [_ev(100, 0)]                       # fix-1 full green
    tr, _ = _run(phase, subset, full, memory=mem)
    assert tr.orchestration_outcome == "green"
    assert mem.invalidations == ["p.C.put"]
    assert _phases_called(phase) == ["cache-fix", "alpha", "beta", "gamma",
                                     "fix-1"]
    assert "STALE" in "\n".join(_events(tr))


def test_beta_compile_break_degrades_to_no_logs():
    phase = FakePhase()
    subset = [(_ev(0, 0, compiled=False, ran=False), []),   # beta broke build
              (_ev(0, 0, compiled=False, ran=False), []),   # repair also broke
              (_ev(2, 0), [])]                              # fix-1 subset green
    full = [_ev(100, 0)]
    tr, strips = _run(phase, subset, full)
    assert tr.orchestration_outcome == "green"
    assert _phases_called(phase) == ["alpha", "beta", "beta-repair", "gamma",
                                     "fix-1"]
    ev = "\n".join(_events(tr))
    assert "NO-LOGS" in ev
    assert strips == [1]                       # probes still stripped
    # gamma got the no-logs marker in its prompt
    gamma_prompt_text = [p for (n, p, _t) in phase.calls if n == "gamma"][0]
    assert "no runtime logs" in gamma_prompt_text


def test_gamma_unparseable_twice_falls_back_to_target_first():
    phase = FakePhase(gamma_texts=["garbage", "still garbage"])
    subset = [(_ev(1, 1), ["RCC_PROBE x"]), (_ev(2, 0), [])]
    full = [_ev(100, 0)]
    mem = FakeMemory()
    tr, _ = _run(phase, subset, full, memory=mem)
    assert tr.orchestration_outcome == "green"
    assert _phases_called(phase) == ["alpha", "beta", "gamma", "gamma-retry",
                                     "fix-1"]
    ev = "\n".join(_events(tr))
    assert "degraded to subgraph-order ranking" in ev
    # degraded run has no graph -> nothing saved to memory even on green
    assert mem.puts == []
    # fix-1 focused on the target (first in subgraph order)
    fix_prompt_text = [p for (n, p, _t) in phase.calls if n == "fix-1"][0]
    assert "p.C.put" in fix_prompt_text and "no causal graph" in fix_prompt_text
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `python3 -m pytest tests/test_rcc_graph.py -q`
Expected: the 4 happy-path tests pass; if any of the 4 new ones fail, the failure text pinpoints the node logic to fix (they are written against the Task 5 implementation — all 8 should pass if Task 5 was implemented exactly as specified).

- [ ] **Step 3: Fix any mismatches, re-run**

Run: `python3 -m pytest tests/test_rcc_graph.py -q`
Expected: 8 passed

- [ ] **Step 4: Run the ENTIRE test suite (no regressions anywhere)**

Run: `python3 -m pytest tests/ -q`
Expected: everything passes (langgraph-dependent files skip if the extra is missing)

- [ ] **Step 5: Commit**

```bash
git add tests/test_rcc_graph.py
git commit -m "test(rcc): memory hit/stale, beta no-logs degrade, gamma fallback scenarios"
```

---

## Deviations to flag during execution

- If `SuiteResult` requires more constructor args than `(compiled, ran, executed, passed, failed)` (e.g. non-defaulted `errors`/`skipped`), mirror how `tests/test_orchestrator.py::_eval` constructs it.
- If `stitch()`'s keyword names differ from `orchestrator_graph.py`'s call (they should not — copy that call exactly), match `orchestrator_graph.py`.
- If `verify._system_for_command` is named differently, find the helper `augment_for_full_run` uses in `abench/verify.py:198` and import that.

## Out of scope (Phase 2 plan)

Runner/config wiring (`orchestration: "rcc"` condition value, `_select_orchestrator`-style dispatch, building the real deps: `build_subgraph` from `workdir/.impact`, `RccMemory` at `rundir/rcc-memory.json`, `strip_probes` over git-changed files via `strip_marked_lines`), metrics additions (APFDc / `rcc_root_rank`, hit and degrade counters), the hit-rate demo script, A/B experiment YAMLs, e2e smoke on the prepared machine.
