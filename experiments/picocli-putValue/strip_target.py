# experiments/picocli-putValue/strip_target.py
"""Replace exactly one method body with a stub (brace matching from the
signature line). Newline-preserving (keepends) so CRLF checkouts survive."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def strip(path: Path, signature: str, stub: str) -> tuple[int, int]:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    hits = [i for i, l in enumerate(lines) if signature in l]
    if not hits:
        sys.exit(f"signature not found in {path}: {signature}")
    if len(hits) > 1:
        sys.exit(f"signature not unique in {path} (lines {[h+1 for h in hits]})")
    sig = hits[0]
    depth, end = 0, None
    for i in range(sig, len(lines)):
        for ch in lines[i]:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end is not None:
            break
    if end is None or end <= sig:
        sys.exit(f"could not brace-match the body from line {sig + 1}")
    nl = "\r\n" if lines[sig].endswith("\r\n") else "\n"
    indent = re.match(r"\s*", lines[sig]).group(0)
    lines[sig:end + 1] = [lines[sig], f"{indent}    {stub}{nl}", f"{indent}}}{nl}"]
    path.write_text("".join(lines), encoding="utf-8")
    return sig + 1, end + 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", type=Path, required=True)
    ap.add_argument("--signature", required=True)
    ap.add_argument("--stub", required=True)
    a = ap.parse_args()
    first, last = strip(a.file, a.signature, a.stub)
    print(f"stripped lines {first}..{last} -> 3-line stub")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
