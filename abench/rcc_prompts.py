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
