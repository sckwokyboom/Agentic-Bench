"""The build_mutation_graph seam (R1) + its builders.

Verified against Graph-Tipper on-machine: the GT structural graph is a PRECOMPUTED
per-target artifact (kgpool stub-builds the CPG + runs the red suite — too heavy for
per-invocation). So the PRIMARY builder LOADS that artifact (shipped in the overlay,
like coverage.json) and strips the target's correct body via parse_gt_graph. The graph
is ALWAYS leak-safe (caller-side structure is body-independent; the target body is
stripped or overridden by the agent's own workdir source). Builders:
- artifact_builder: load a precomputed GT graph.json -> parse_gt_graph. PRIMARY.
- llm_builder: one phase_runner call -> MutationGraph JSON. Fallback / callee enricher.
- gt_kgpool_builder: run GT kgpool to PRECOMPUTE the artifact (offline helper, where GT
  is installed) — not a runtime dependency.
abench CONSUMES GT output; it never modifies GT."""
from __future__ import annotations

import json
from pathlib import Path

from .rcc_gt_parse import parse_gt_graph
from .rcc_mutation_graph import MgEdge, MgVertex, MutationGraph


def parse_mgraph_json(text: "str | None") -> "MutationGraph | None":
    """First JSON object in `text` with list vertices+edges -> MutationGraph."""
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


def artifact_builder(workdir, target_fqn, coverage, *, artifact_path,
                     target_source=None) -> "MutationGraph | None":
    """PRIMARY: load a precomputed GT graph.json artifact -> leak-safe MutationGraph.
    None on a missing/corrupt artifact (caller degrades to plain phased)."""
    try:
        gj = json.loads(Path(artifact_path).read_text())
    except (OSError, ValueError):
        return None
    return parse_gt_graph(gj, target_source=target_source)


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
    """Fallback builder: one LLM call -> MutationGraph. None if unparseable."""
    out = phase_runner("build_graph", _build_graph_prompt(target_fqn, coverage),
                       ["read", "grep"])
    return parse_mgraph_json(getattr(out, "text", None))


def gt_kgpool_builder(workdir, target_fqn, coverage, *, gt_home, out_dir=None,
                      timeout_s=1800, runner=None) -> "MutationGraph | None":
    """PRECOMPUTE helper: run Graph-Tipper kgpool to build the graph.json artifact for
    a target, then parse it. Heavy (Joern + red suite) — an OFFLINE one-shot to produce
    the shipped artifact, not a per-invocation call. Best-effort -> None on failure."""
    import os
    import subprocess

    def _default_runner(cmd, cwd, env):
        return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True,
                              text=True, timeout=timeout_s)
    runner = runner or _default_runner
    out_dir = Path(out_dir or (Path(workdir) / ".rcc-graph"))
    try:
        cmd = ["python3", "-m", "harness.kgpool.make", "--project", str(workdir),
               "--target", target_fqn, "--out", str(out_dir), "--skip-jacoco"]
        env = dict(os.environ, PYTHONPATH=str(gt_home))
        runner(cmd, str(gt_home), env)
        gj = json.loads((out_dir / "knowledge-graph.json").read_text())
        return parse_gt_graph(gj)
    except Exception:
        return None


def build_mutation_graph(workdir, target_fqn, coverage, *, builder="artifact", **kw):
    """Dispatch: 'artifact' (primary — needs artifact_path), 'llm' (needs phase_runner),
    'gt' (precompute — needs gt_home). Unknown/failed -> None (caller degrades)."""
    if builder == "llm":
        return llm_builder(workdir, target_fqn, coverage, **kw)
    if builder == "gt":
        return gt_kgpool_builder(workdir, target_fqn, coverage, **kw)
    return artifact_builder(workdir, target_fqn, coverage, **kw)
