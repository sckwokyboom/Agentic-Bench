"""Turn a Graph-Tipper graph.json into the leak-safe, size-trimmed, gzipped RCC
mutation-graph artifact shipped in an experiment overlay.

The overlay artifact makes the rcc condition run its GT-graph arm (builder=artifact)
instead of the LLM-builder fallback. Leak-safety: the target's `current_body` (the
reference/correct implementation) is DROPPED here AND `parse_gt_graph` never reads it
either — the caller-side structure is stub-built and body-independent, so it is safe to
ship. Also drops the per-chain test `sliced_body` (unused by the parser) and trims each
step's `call_site`/`args` to what the parser needs — cutting ~9MB → ~90KB gzipped.

Usage:
  python3 scripts/rcc_ship_artifact.py \
      --graph experiments/picocli-putValue/gt-out/slice-work/357b6bd1af378e00.graph.json \
      --out   experiments/picocli-putValue/overlays/impact-artifacts/.impact/mutation-graph.json.gz
Then verify: the runner's resolve_artifact() finds it and artifact_builder loads it.
"""
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path


def trim(graph_json: dict) -> dict:
    """Drop the leak (target.current_body) + the parser-unused bulk (chain test bodies,
    per-step call_site.code / arg values), keeping exactly what parse_gt_graph consumes:
    target/method_bodies metadata + chains (caller_ref/callee_ref/call_site{file,line}/
    args[{origin}])."""
    d = json.loads(json.dumps(graph_json))          # copy — don't mutate the caller's
    (d.get("target") or {}).pop("current_body", None)
    # local_context {siblings, used_types} is NOT read by parse_gt_graph and its
    # `used_types` can hint at the fix's dependencies (a soft leak) — drop it.
    d.pop("local_context", None)
    for c in d.get("chains", []):
        (c.get("test") or {}).pop("sliced_body", None)
        for st in c.get("steps", []):
            cs = st.get("call_site")
            if isinstance(cs, dict):
                st["call_site"] = {"file": cs.get("file"), "line": cs.get("line")}
            st["args"] = [{"origin": a.get("origin")} for a in (st.get("args") or [])]
    return d


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", required=True, help="GT graph.json (from kgpool/slice-work)")
    ap.add_argument("--out", required=True, help="target .json.gz in the overlay's .impact")
    args = ap.parse_args(argv)

    raw = json.loads(Path(args.graph).read_text())
    trimmed = trim(raw)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(gzip.compress(json.dumps(trimmed).encode("utf-8")))

    # provenance + a leak assertion the operator can eyeball
    correct_body = (raw.get("target") or {}).get("current_body") or ""
    blob = json.dumps(trimmed)
    leaked = bool(correct_body) and correct_body[:80] in blob
    print(f"wrote {out} ({out.stat().st_size/1e6:.3f} MB gz) — "
          f"target={raw.get('target', {}).get('fqn')} chains={len(trimmed.get('chains', []))}")
    print(f"LEAK check (target correct body in artifact): {leaked}")
    return 1 if leaked else 0


if __name__ == "__main__":
    raise SystemExit(main())
