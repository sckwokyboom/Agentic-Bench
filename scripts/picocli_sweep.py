#!/usr/bin/env python3
"""Generate the picocli METHOD-RESTORATION A/B: baseline vs rcc, over many methods.

Why this exists. Every public-benchmark measurement so far turned out to be about
recall, not debugging: Defects4J is exhausted (45/46 solved), and with the tests
hidden both jackson-core and fastjson2 reproduced the reference fix VERBATIM (median
similarity 1.00). On a task the model remembers, rcc can only ever look like
overhead — recall is instant, so the causal loop pays for something already known.

This task shape is different. One method body is replaced by a stub; the API stays.
The agent must implement it so the suite passes. The candidates form a real call
chain inside TextTable — addRowValues -> addEmptyRow -> unindent -> putValue ->
reindent — with a 4-to-46-line difficulty gradient and ~400 covering tests each,
which is exactly the shape rcc is built for: a failure far from its cause, with many
tests failing at once.

MEMORISATION STILL APPLIES. picocli is public, so the model may recall the original
body rather than derive one. That is not fatal here, because the harness measures it:
`reference_path` makes target_similarity a per-method recall detector. Read the digest
with that column first — a method restored verbatim cannot demonstrate anything about
a repair loop, exactly as jackson-core could not.

Arms:
  baseline — plain agent, no orchestration, no overlay (a raw agent, deliberately)
  rcc      — the causal loop over the GROUND-TRUTH mutation graph

Both arms get restore_non_target_before_verify, so the verdict is about the method
under repair rather than collateral edits, and both are constrained identically.

    python3 scripts/picocli_sweep.py                     # default gradient, 2 reps
    python3 scripts/picocli_sweep.py --methods putValue,addRowValues --reps 3
    python3 scripts/picocli_sweep.py --no-graph          # fixtures only (fast)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXP = REPO / "experiments" / "picocli-putValue"
ORIGINAL = EXP / "original"
ARTIFACTS = EXP / "overlays" / "impact-artifacts" / ".impact"

MODEL = "deepseek/deepseek-v4-flash"
STUB = 'throw new UnsupportedOperationException("TODO: implement");'
#: The leak guard looks for this in every published artifact — see check_no_leak().
STUB_MARK = 'UnsupportedOperationException("TODO'

#: The default gradient: one call chain, 4 to 46 body lines, ~400 covering tests each.
#: putValue is the known-hard end (46 lines of SPAN/WRAP logic); reindent the easy end.
DEFAULT_METHODS = ["reindent", "addEmptyRow", "unindent", "forDefaultColumns",
                   "addRowValues", "toString", "putValue"]

EXPERIMENT = """\
# AUTO-GENERATED method-restoration A/B for picocli TextTable.{method}
# {tests} covering tests | {lines}-line body replaced by a stub
#
# baseline = raw agent. rcc = causal loop over the ground-truth mutation graph.
# Read target_similarity FIRST: picocli is public, so a verbatim restoration means
# the model recalled the body and this method measures recall, not repair.
name: picocli-{method}-ab
fixture_path: ./checkout           # the stub tree the agent sees
reference_path: {reference}        # the real picocli tree (target_similarity)
task_prompt: ./task.md
system_prompt: {system}
model: {model}
timeout_s: 1800
repetitions: {reps}
output_dir: ./runs
opencode:
  agent: abench
  providers:
    - id: deepseek
      name: DeepSeek API
      base_url: https://api.deepseek.com/v1
      models: [deepseek-v4-flash, deepseek-chat, deepseek-reasoner]
      api_key_env: DEEPSEEK_API_KEY
  sandbox:
    mode: none
orchestration:
  target_label: the TextTable.{method} method
  max_diagnose_iters: 8
  no_progress_limit: 2
  cluster_cap: 5
  rcc_max_attempts: 2
  rcc_subset_class_cap: 15
  rcc_revert_to_best: true         # part of the rcc STRATEGY (see config docs)
conditions:
{conditions}
target_file: src/main/java/picocli/CommandLine.java
target_methods: [{method}]
verify:
  timeout_s: 1800
metrics:
  test_command_patterns:
    - "(mvn|mvnw)( |$)"
    - "(gradle|gradlew)( |$)"
"""

TASK = """\
The body of `{cls}.{method}` in `src/main/java/picocli/CommandLine.java` has been
replaced with a stub that throws UnsupportedOperationException.

Implement it so the project's test suite passes. Keep the existing signature and do
not change the tests.
"""


def load_index() -> tuple[dict, dict]:
    """coverage.json (tests per method) + methods.json (declaration spans)."""
    cov = json.loads((ARTIFACTS / "coverage.json").read_text(encoding="utf-8"))
    meths = json.loads((ARTIFACTS / "methods.json").read_text(encoding="utf-8"))
    return cov, meths


def body_span(src: list[str], decl_line: int) -> tuple[int, int]:
    """(first, last) 0-based line indices of the brace-matched body, decl included."""
    depth, start, i = 0, None, decl_line - 1
    for j in range(i, min(i + 500, len(src))):
        for ch in src[j]:
            if ch == "{":
                depth += 1
                if start is None:
                    start = j
            elif ch == "}":
                depth -= 1
                if depth == 0 and start is not None:
                    return start, j
    raise ValueError(f"could not brace-match a body from line {decl_line}")


def strip_body(path: Path, decl_line: int) -> int:
    """Replace the body at decl_line with the stub. Returns lines removed.

    Line-addressed rather than signature-matched: picocli has overloads and repeated
    signatures, and a text match silently picks the wrong one.
    """
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    first, last = body_span(lines, decl_line)
    nl = "\r\n" if lines[first].endswith("\r\n") else "\n"
    indent = re.match(r"\s*", lines[first]).group(0)
    removed = last - first + 1
    lines[first:last + 1] = [lines[first].rstrip("\r\n") + nl,
                             f"{indent}    {STUB}{nl}", f"{indent}}}{nl}"]
    path.write_text("".join(lines), encoding="utf-8")
    return removed


def split_params(sig: str) -> list[str]:
    """Simple type names of a declaration's parameters, generic-aware."""
    inner = sig[sig.index("(") + 1:sig.rindex(")")] if "(" in sig else ""
    parts, depth, cur = [], 0, ""
    for ch in inner:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur); cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)
    out = []
    for p in parts:
        p = p.strip().replace("final ", "")
        # Varargs otherwise lose their type entirely (addRowValues(Text...) resolved
        # to no parameters at all). Graph-Tipper spells them `Text...` in its own
        # slices, and `Text[]` made its slice step exit 2 with the target not found.
        varargs = "..." in p
        toks = p.replace("...", " ").split()
        if len(toks) < 2:
            continue
        t = " ".join(toks[:-1])            # everything but the parameter name
        arr = "[]" * t.count("[]")
        t = t.replace("[]", "").split("<")[0].rsplit(".", 1)[-1]   # simple name
        out.append(t + arr + ("..." if varargs else ""))
    return out


def reanchor(methods_path: Path, original: Path, seed: Path) -> int:
    """Move the target file's method spans from ORIGINAL to STUB coordinates.

    joern indexed the original tree, but the agent edits the stripped one, and the
    stub is 3 lines where the body was — so every span below the target is off. rcc
    would then point at the wrong lines. Ported from prepare.py, which does exactly
    this for the committed putValue artifacts.
    """
    import difflib
    a = original.read_text(encoding="utf-8").splitlines()
    b = seed.read_text(encoding="utf-8").splitlines()
    lmap: dict[int, int] = {}
    for tag, i1, i2, j1, _j2 in difflib.SequenceMatcher(a=a, b=b,
                                                        autojunk=False).get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                lmap[i1 + k + 1] = j1 + k + 1
        else:                       # collapse a replaced block onto the seed's start
            for k in range(i1, i2):
                lmap[k + 1] = j1 + 1
    base = original.name
    methods = json.loads(methods_path.read_text(encoding="utf-8"))
    moved = 0
    for loc in methods.values():
        if not str(loc.get("file", "")).endswith(base):
            continue
        s = lmap.get(loc["start"])
        if s is None:
            continue
        e = max(lmap.get(loc["end"], s), s)
        if [s, e] != [loc["start"], loc["end"]]:
            loc["start"], loc["end"] = s, e
            moved += 1
    methods_path.write_text(json.dumps(methods, indent=0), encoding="utf-8")
    return moved


def pack_overlay(gt_out: Path, overlay: Path, fqn: str,
                 original: Path, seed: Path) -> str | None:
    """Assemble the rcc overlay from a produce_artifacts run. None on success.

    Graph-Tipper writes `impact/` (indices) and `slice-work/<hash>.graph.json` (the
    mutation graph) — but rcc reads `.impact/mutation-graph.json[.gz]`, so the graph
    has to be selected by target and gzipped into place. Getting this wrong is silent:
    the first version copied from a path that does not exist, published an EMPTY
    overlay, and every rcc run would have died at rcc_strict with no graph.
    """
    src = gt_out / "impact"
    if not src.is_dir():
        return f"no {src} — produce_artifacts wrote nothing to copy"
    shutil.copytree(src, overlay / ".impact")

    graphs = sorted((gt_out / "slice-work").glob("*.graph.json"))
    chosen = None
    for g in graphs:
        try:
            if json.loads(g.read_text(encoding="utf-8")).get("target", {}).get("fqn") == fqn:
                chosen = g
                break
        except (OSError, json.JSONDecodeError):
            continue
    if chosen is None:
        return (f"no mutation graph for {fqn} among "
                f"{[g.name for g in graphs] or 'no *.graph.json at all'}")
    # SCRUB before publishing. produce_artifacts' --body-from only swaps the body in
    # the markdown slices — its leak guard covers those alone — while the graph keeps
    # target.current_body as found in the FULL tree, i.e. the reference implementation.
    # The shipped putValue artifact has that field empty, so it was scrubbed too. Left
    # in, the rcc arm reads the answer out of its own graph and every number it
    # produces is meaningless.
    import gzip
    graph = json.loads(chosen.read_text(encoding="utf-8"))
    stub_body = ""
    try:
        seed_lines = seed.read_text(encoding="utf-8").splitlines(keepends=True)
        ls = graph.get("target", {}).get("line_start")
        if ls:
            f0, l0 = body_span(seed_lines, ls)
            stub_body = "".join(seed_lines[f0:l0 + 1]).rstrip("\r\n")
    except (OSError, ValueError):
        stub_body = ""
    if STUB_MARK not in stub_body:            # never publish a body we cannot vouch for
        stub_body = ""
    graph.setdefault("target", {})["current_body"] = stub_body
    graph.get("method_bodies", {}).pop(fqn, None)
    with gzip.open(overlay / ".impact" / "mutation-graph.json.gz", "wt",
                   encoding="utf-8") as fh:
        json.dump(graph, fh)

    mj = overlay / ".impact" / "methods.json"
    if mj.is_file():
        reanchor(mj, original, seed)
    return None


def check_no_leak(overlay: Path, reference_body: str) -> str | None:
    """Refuse to publish an overlay that carries the answer.

    The rcc arm reads these artifacts. If the reference body reaches them, rcc is
    handed the solution and every number it produces is worthless — the failure this
    guard exists to make impossible.
    """
    import gzip
    needle = " ".join(reference_body.split())[:200]
    if len(needle) < 40:
        return None                        # too short to fingerprint reliably
    for f in sorted(overlay.rglob("*")):
        if not f.is_file():
            continue
        try:
            # The graph ships gzipped and is the ONE file rcc actually reads — the
            # first version skipped .gz and so never inspected it.
            raw = (gzip.open(f, "rt", encoding="utf-8", errors="replace").read()
                   if f.suffix == ".gz"
                   else f.read_text(encoding="utf-8", errors="replace"))
        except (OSError, EOFError):
            continue
        # JSON stores the body with ESCAPED newlines, so collapsing real whitespace
        # alone never matched it — that is precisely how a leaked reference body in
        # the graph passed this guard the first time. Neutralise the escapes too.
        flat = " ".join(raw.replace("\\n", " ").replace("\\t", " ")
                        .replace("\\r", " ").split())
        if needle in flat:
            return f"reference body found in {f.relative_to(overlay)}"
    return None


def produce_graph(gt: Path, method: str, fqn: str, decl: str, checkout: Path,
                  out: Path, tests: str, timeout: int) -> str | None:
    """Build the ground-truth mutation graph for one target. None on success."""
    cls = fqn.rsplit(".", 1)[0].split("$")[-1]
    params = ",".join(split_params(decl))
    slice_target = (f"src/main/java/picocli/CommandLine.java#{cls}.{method}({params})")
    cmd = [sys.executable, "-m", "harness.impact.produce_artifacts",
           "--project", str(ORIGINAL), "--target-fqn", fqn,
           "--slice-target", slice_target, "--tests", tests,
           # Graph context comes from the FULL tree, but the published body must be
           # the agent-visible stub — the real body is the answer.
           "--out", str(out), "--body-from", str(checkout), "--force"]
    env = dict(os.environ, PYTHONPATH=str(gt))
    # The artifact build downloads byte-buddy from Maven Central, and a python.org
    # Python.framework ships without CA certificates — every graph build died on
    # CERTIFICATE_VERIFY_FAILED. certifi is already a dependency here, so point the
    # child at its bundle rather than requiring "Install Certificates.command".
    if "SSL_CERT_FILE" not in env:
        try:
            import certifi
            env["SSL_CERT_FILE"] = env["REQUESTS_CA_BUNDLE"] = certifi.where()
        except ImportError:
            pass
    # A previous attempt's slice-work/ makes produce_artifacts find two budget
    # slices and abort — keeping failed fixtures for diagnosis turned every retry
    # into a different failure. Start from an empty output dir.
    shutil.rmtree(out, ignore_errors=True)
    t0 = time.monotonic()
    p = subprocess.run(cmd, cwd=gt, env=env, capture_output=True,
                       text=True, errors="replace", timeout=timeout)
    dt = time.monotonic() - t0
    if p.returncode != 0:
        out.parent.mkdir(parents=True, exist_ok=True)
        log = out.parent / "produce_artifacts.log"
        log.write_text(f"$ {' '.join(cmd)}\n\n--- stdout ---\n{p.stdout}\n"
                       f"--- stderr ---\n{p.stderr}", encoding="utf-8")
        cause = [ln for ln in (p.stderr or "").strip().splitlines()
                 if ln.strip() and not ln.startswith((" ", "\t"))][-1:] or ["(no stderr)"]
        return f"produce_artifacts failed in {dt:.0f}s: {cause[0][:160]} — see {log}"
    print(f"      graph built in {dt / 60:.1f} min")
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=REPO / "picocli-sweep")
    ap.add_argument("--methods", help="comma-separated (default: the gradient)")
    ap.add_argument("--reps", type=int, default=2,
                    help="repetitions per arm; 2+ recommended (agents are high-variance)")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--tests", default="picocli.HelpTest,picocli.TextTableTest",
                    help="test classes captured for coverage during graph build")
    ap.add_argument("--graph-timeout", type=int, default=3600)
    ap.add_argument("--no-graph", action="store_true",
                    help="build fixtures only; rcc needs the graph, so this is for "
                         "checking the strip step quickly")
    ap.add_argument("--force", action="store_true", help="rebuild existing fixtures")
    a = ap.parse_args()
    # Every path handed to produce_artifacts must be absolute: it runs with
    # cwd=Graph-Tipper, so a relative --root wrote the artifacts into the
    # Graph-Tipper checkout and the sweep found nothing.
    a.root = a.root.resolve()

    if not ORIGINAL.is_dir():
        print(f"missing {ORIGINAL} — run experiments/picocli-putValue/prepare.py first")
        return 2
    # The reference tree must be PRISTINE picocli. It is not tracked in git — it is
    # cloned at a pinned SHA — so it is easy to strip in place by accident, and the
    # consequences are silent: reference_path drives target_similarity, so a stubbed
    # reference would compare the agent's work against a stub and call it a match.
    # It also breaks the coverage capture (a stubbed putValue failed 175 of 267 tests
    # after 564 seconds, with the real cause nowhere in the error).
    ref_src = ORIGINAL / "src/main/java/picocli/CommandLine.java"
    if ref_src.is_file() and STUB_MARK in ref_src.read_text(encoding="utf-8"):
        print(f"CONTAMINATED reference tree: {ref_src} already contains a stub.\n"
              f"  {ORIGINAL} must be untouched picocli — it is the similarity "
              "reference AND the tree the coverage capture runs its tests on.\n"
              "  Restore it:  python3 experiments/picocli-putValue/prepare.py "
              "--only fixtures --force")
        return 2
    gt = None
    if not a.no_graph:
        try:
            from abench.libraries import load_registry
            reg = load_registry().get("graph-tipper")
            gt = Path(reg) if reg else None
        except Exception:
            gt = None
        gt = gt or (Path(os.environ["GRAPH_TIPPER_HOME"])
                    if os.environ.get("GRAPH_TIPPER_HOME") else None)
        if not gt or not gt.is_dir():
            print("Graph-Tipper not found: `abench lib add graph-tipper <path>` or "
                  "set GRAPH_TIPPER_HOME (or pass --no-graph to skip graph build)")
            return 2

    cov, meths = load_index()
    by_short = {k.rsplit(".", 1)[-1]: k for k in cov}
    want = [m.strip() for m in a.methods.split(",")] if a.methods else DEFAULT_METHODS

    a.root.mkdir(parents=True, exist_ok=True)
    src_file = "src/main/java/picocli/CommandLine.java"
    made, skipped = [], []
    lines_out = ["#!/usr/bin/env bash", "set -uo pipefail",
                 "# picocli method-restoration A/B: baseline vs rcc. Resumable.",
                 'ROOT="$(cd "$(dirname "$0")" && pwd)"', ""]

    for m in want:
        fqn = by_short.get(m)
        if not fqn:
            skipped.append(f"{m}: not in coverage.json (known: "
                           f"{', '.join(sorted(by_short)[:6])}…)")
            continue
        entry = meths.get(fqn)
        if not entry or src_file not in entry.get("file", ""):
            skipped.append(f"{m}: no declaration span in methods.json")
            continue

        d = a.root / m
        if (d / "experiment.yaml").is_file() and not a.force:
            made.append((m, len(cov[fqn]), "reused"))
            lines_out += [f'echo "=== {m} ==="', f'D="$ROOT/{m}"',
                          'if ls "$D"/runs/*/*/*/rep_*/metrics.json >/dev/null 2>&1; then',
                          f'  echo "  SKIP {m}: already has runs (rm -rf $D/runs to redo)"',
                          "else",
                          f'  ( cd "$D" && abench run experiment.yaml ) || echo "  !! failed: {m}"',
                          "fi", ""]
            continue

        print(f"  … {m}: copying the tree")
        checkout = d / "checkout"
        if checkout.exists():
            shutil.rmtree(checkout)
        d.mkdir(parents=True, exist_ok=True)
        shutil.copytree(ORIGINAL, checkout, symlinks=True)

        target = checkout / src_file
        original_src = (ORIGINAL / src_file).read_text(encoding="utf-8").splitlines(keepends=True)
        first, last = body_span(original_src, entry["start"])
        reference_body = "".join(original_src[first:last + 1])
        try:
            removed = strip_body(target, entry["start"])
        except ValueError as exc:
            skipped.append(f"{m}: {exc}")
            shutil.rmtree(d, ignore_errors=True)
            continue
        if STUB_MARK not in target.read_text(encoding="utf-8"):
            skipped.append(f"{m}: stub not present after stripping")
            shutil.rmtree(d, ignore_errors=True)
            continue

        if not a.no_graph:
            print(f"  … {m}: building the ground-truth graph (can take many minutes)")
            err = produce_graph(gt, m, fqn, original_src[first], checkout,
                                d / "gt-out", a.tests, a.graph_timeout)
            if err:
                # Deliberately NOT removed: the failure log lives under gt-out/ and
                # deleting it was why the first WSL failure could not be diagnosed.
                skipped.append(f"{m}: {err}")
                continue
            overlay = d / "overlay"
            shutil.rmtree(overlay, ignore_errors=True)
            err = pack_overlay(d / "gt-out", overlay, fqn,
                               ORIGINAL / src_file, checkout / src_file)
            if err:
                skipped.append(f"{m}: {err}")
                shutil.rmtree(d, ignore_errors=True)
                continue
            leak = check_no_leak(overlay, reference_body)
            if leak:
                skipped.append(f"{m}: LEAK GUARD — {leak}")
                shutil.rmtree(d, ignore_errors=True)
                continue

        (d / "task.md").write_text(TASK.format(
            cls=fqn.rsplit(".", 1)[0].split("$")[-1], method=m), encoding="utf-8")
        sys_prompt = EXP / "prompts" / "system.md"
        # Without a graph the rcc arm has no overlay and the experiment will not even
        # load, so --no-graph emits the baseline arm alone: still a runnable smoke test
        # of the strip step rather than a file that only errors.
        conditions = ["  - {name: baseline, augmentation: null, tools: [], "
                      "restore_non_target_before_verify: true}"]
        if not a.no_graph:
            conditions += ["  - name: rcc", "    orchestration: rcc",
                           "    overlay: ./overlay",
                           "    restore_non_target_before_verify: true"]
        (d / "experiment.yaml").write_text(EXPERIMENT.format(
            method=m, tests=len(cov[fqn]), lines=removed, model=a.model, reps=a.reps,
            conditions="\n".join(conditions),
            reference=os.path.relpath(ORIGINAL, d),
            system=os.path.relpath(sys_prompt, d)), encoding="utf-8")
        made.append((m, len(cov[fqn]), f"{removed} lines stripped"))
        lines_out += [f'echo "=== {m} ==="', f'D="$ROOT/{m}"',
                      'if ls "$D"/runs/*/*/*/rep_*/metrics.json >/dev/null 2>&1; then',
                      f'  echo "  SKIP {m}: already has runs (rm -rf $D/runs to redo)"',
                      "else",
                      f'  ( cd "$D" && abench run experiment.yaml ) || echo "  !! failed: {m}"',
                      "fi", ""]

    script = a.root / "run_sweep.sh"
    script.write_text("\n".join(lines_out))
    script.chmod(0o755)
    print(f"\nbuilt {len(made)} fixture(s) under {a.root}/ + {script}")
    for m, t, note in made:
        print(f"  {m:20} {t:>4} covering tests  ({note})")
    if skipped:
        print("\nSKIPPED:")
        for s in skipped:
            print(f"  {s}")
    arms = 1 if a.no_graph else 2
    print(f"\nRuns: {len(made)} methods x {arms} arm(s) x {a.reps} rep(s) = "
          f"{len(made) * arms * a.reps} agent sessions.")
    if a.no_graph:
        print("NOTE: --no-graph emitted the BASELINE ARM ONLY (rcc needs the mutation "
              "graph). Re-run without --no-graph --force to get the A/B.")
    print("Read the digest's target_similarity column first: a verbatim restoration "
          "means the model recalled picocli's own body, so that method measures "
          "recall rather than repair.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
