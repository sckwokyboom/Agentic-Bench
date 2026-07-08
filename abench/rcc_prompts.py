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
