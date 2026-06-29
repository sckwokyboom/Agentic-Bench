"""Export deduplicated call-site snippets for medoid call chains.

Graph-Tipper emits a ``.budget.md`` file describing each medoid cluster and a
JSON sidecar containing the representative chains and their call-site slices.
This script turns those per-chain slices into one compact, method-level block
and inserts it into an existing Markdown augmentation.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


HEADING = "## Chain methods (call-site snippets)"
CLUSTER_RE = re.compile(
    r"^#### [^\n]+\n"
    r".*?^\*\*Entry-point:\*\* `([^`]+)`"
    r".*?^\*\*Primary representative:\*\* `([^`]+)`",
    re.MULTILINE | re.DOTALL,
)


@dataclass(frozen=True)
class Medoid:
    entry_fqn: str
    test_fqn: str


def parse_medoids(budget_markdown: str) -> list[Medoid]:
    """Read medoid identities in their rendered cluster order."""
    return [Medoid(entry, test) for entry, test in CLUSTER_RE.findall(budget_markdown)]


def find_representative_chain(chains: list[dict], medoid: Medoid) -> dict:
    """Match the sidecar chain selected as the cluster's representative."""
    candidates = []
    for chain in chains:
        test = chain.get("test")
        test_fqn = test.get("fqn") if isinstance(test, dict) else test
        if test_fqn != medoid.test_fqn:
            continue
        steps = chain.get("steps") or []
        if steps and steps[0].get("calleeFqn") == medoid.entry_fqn:
            return chain
        candidates.append(chain)
    if candidates:
        return candidates[0]
    raise ValueError(
        f"representative chain not found for {medoid.test_fqn} "
        f"entering {medoid.entry_fqn}"
    )


def simple_method(fqn: str) -> str:
    """Render a fully qualified method name as ``Class.method``."""
    if "." not in fqn:
        return fqn
    owner, method = fqn.rsplit(".", 1)
    owner = re.split(r"[.$]", owner)[-1]
    return f"{owner}.{method}"


def compact_snippet(snippet: str, callee_fqn: str, max_lines: int = 8) -> str:
    """Keep the caller signature and a small window around the callee invocation."""
    lines = snippet.rstrip().splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines)

    callee_name = callee_fqn.rsplit(".", 1)[-1]
    call_line = next(
        (index for index in range(len(lines) - 1, 0, -1)
         if re.search(rf"\b{re.escape(callee_name)}\s*\(", lines[index])),
        len(lines) - 1,
    )

    # Signature + a five-line call window leaves room for gap markers.
    window_start = max(1, call_line - 4)
    window_end = min(len(lines), call_line + 2)
    while window_end - window_start > max_lines - 3:
        window_start += 1

    result = [lines[0]]
    if window_start > 1:
        result.append("    // ...")
    result.extend(lines[window_start:window_end])
    if window_end < len(lines):
        result.append("    // ...")
    return "\n".join(result[:max_lines])


def collect_unique_steps(
    medoids: list[Medoid],
    chains: list[dict],
    target_fqn: str,
) -> list[dict]:
    """Collect each method-level edge once, excluding test-to-entry steps."""
    result = []
    seen: set[tuple[str, str]] = set()
    for medoid in medoids:
        chain = find_representative_chain(chains, medoid)
        for step in (chain.get("steps") or [])[1:]:
            caller = step.get("callerFqn", "")
            callee = step.get("calleeFqn", "")
            edge = (caller, callee)
            if caller == target_fqn:
                continue
            if not all(edge) or edge in seen:
                continue
            seen.add(edge)
            result.append(step)
    return result


def render_block(
    steps: list[dict],
    target_fqn: str,
    max_lines: int = 8,
    overrides: dict[str, str] | None = None,
) -> str:
    """Render the standalone Markdown block inserted after the medoid section."""
    lines = [
        HEADING,
        "",
        "Use the full chains above to choose methods to inspect and to place temporary",
        "`//[probe]` diagnostics along the relevant path. These compact fragments show",
        "how arguments and calls flow toward `putValue`; each method-level edge appears",
        "once. They show caller code only—the body of the target method is intentionally",
        "omitted.",
        "",
    ]
    overrides = overrides or {}
    for step in steps:
        caller = step["callerFqn"]
        callee = step["calleeFqn"]
        edge = f"{simple_method(caller)} → {simple_method(callee)}"
        edge_key = f"{caller} -> {callee}"
        snippet = overrides.get(edge_key, step.get("snippet") or "").strip()
        lines.append(f"- `{edge}`:")
        if not snippet or snippet == "(call site not located)":
            lines.append(
                "  - Call site not located in source; this is a callback or virtual "
                "transition in the representative chain."
            )
        else:
            lines.append("```java")
            lines.extend(compact_snippet(snippet, callee, max_lines).splitlines())
            lines.append("```")
        lines.append("")

    block = "\n".join(lines).rstrip() + "\n"
    if target_fqn in {step.get("callerFqn") for step in steps}:
        raise ValueError(f"refusing to render the target method body: {target_fqn}")
    return block


def insert_block(markdown: str, block: str) -> str:
    """Insert or replace the generated block immediately after the medoid section."""
    if HEADING in markdown:
        start = markdown.index(HEADING)
        next_section = markdown.find("\n---\n", start)
        if next_section < 0:
            raise ValueError(f"separator after {HEADING!r} not found")
        remainder = markdown[next_section + len("\n---\n") :].lstrip("\n")
        markdown = markdown[:start] + remainder

    medoid_heading = "## Clustered call chains (medoids)"
    start = markdown.find(medoid_heading)
    if start < 0:
        raise ValueError(f"{medoid_heading!r} not found")
    separator = markdown.find("\n---\n", start)
    if separator < 0:
        raise ValueError(f"separator after {medoid_heading!r} not found")
    insertion = separator + len("\n---\n")
    return markdown[:insertion] + "\n" + block + "\n---\n" + markdown[insertion:]


def export(
    budget_path: Path,
    sidecar_path: Path,
    slice_path: Path,
    target_fqn: str,
    max_lines: int = 8,
    overrides_path: Path | None = None,
) -> int:
    budget_markdown = budget_path.read_text(encoding="utf-8")
    medoids = parse_medoids(budget_markdown)
    if not medoids:
        raise ValueError(f"no medoid clusters found in {budget_path}")
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    steps = collect_unique_steps(medoids, sidecar.get("chains", []), target_fqn)
    overrides = (
        json.loads(overrides_path.read_text(encoding="utf-8"))
        if overrides_path is not None
        else {}
    )
    block = render_block(steps, target_fqn, max_lines, overrides)
    updated = insert_block(slice_path.read_text(encoding="utf-8"), block)
    slice_path.write_text(updated, encoding="utf-8")
    return len(steps)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", required=True, type=Path)
    parser.add_argument("--sidecar", required=True, type=Path)
    parser.add_argument("--slice", required=True, type=Path)
    parser.add_argument("--target-fqn", required=True)
    parser.add_argument("--max-lines", type=int, default=8)
    parser.add_argument(
        "--overrides",
        type=Path,
        help="Optional JSON map of full 'caller -> callee' edges to source snippets",
    )
    args = parser.parse_args()
    count = export(
        args.budget,
        args.sidecar,
        args.slice,
        args.target_fqn,
        args.max_lines,
        args.overrides,
    )
    print(f"wrote {count} unique call-site edges to {args.slice}")


if __name__ == "__main__":
    main()
