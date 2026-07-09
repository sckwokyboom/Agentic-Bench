"""RapidCausalCoder prompt builders (Alpha/Beta/Gamma/fix) + Gamma JSON parsing
+ CausalRank. Pure text/data functions — no I/O, no LLM calls (the graph node
calls phase_runner with these strings). Alpha/Beta/Gamma render the R2
PromptSlice (a dict from rcc_graph_layers.render_slice) rather than the raw
MutationGraph."""
from __future__ import annotations

import json

from .orchestrator import _cap, _fmt_cluster

PROBE_MARKER = "//[probe]"
PROBE_PREFIX = "RCC_PROBE"
_MAX_SPECS_CHARS = 4000
_MAX_GRAPH_CHARS = 4000
_MAX_LOG_LINES = 200

GAMMA_FORMAT_REMINDER = (
    "\n\nREMINDER: your previous answer was not parseable. Return ONLY the JSON "
    "object described above — no prose, no markdown fences.")


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
