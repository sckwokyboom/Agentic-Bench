"""RapidCausalCoder prompt builders (Alpha/Beta/Gamma/fix) + Gamma JSON parsing
+ CausalRank. Pure text/data functions — no I/O, no LLM calls (the graph node
calls phase_runner with these strings)."""
from __future__ import annotations

import json

from .orchestrator import _cap, _fmt_cluster
from .rcc_mutation_graph import MutationGraph

PROBE_MARKER = "//[probe]"
PROBE_PREFIX = "RCC_PROBE"
_MAX_SPECS_CHARS = 4000
_MAX_GRAPH_CHARS = 4000
_MAX_LOG_LINES = 200

GAMMA_FORMAT_REMINDER = (
    "\n\nREMINDER: your previous answer was not parseable. Return ONLY the JSON "
    "object described above — no prose, no markdown fences.")


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
