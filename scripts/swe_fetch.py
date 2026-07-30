#!/usr/bin/env python3
"""Download native Multi-SWE-bench Java datasets by short name, and validate them.

The dataset must be the NATIVE ByteDance records (org/repo/number/base.sha/test_patch/
fix_patch). The flat HF SWE-bench schema looks similar and silently produces unusable
fixtures, so every download is schema-checked before it is accepted.

    python3 scripts/swe_fetch.py --list
    python3 scripts/swe_fetch.py jackson-core
    python3 scripts/swe_fetch.py jackson-core gson mockito --out ~/msb-data
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

_HF = ("https://huggingface.co/datasets/ByteDance-Seed/Multi-SWE-bench"
       "/resolve/main/java/")

#: short name -> the repo's dataset file, verified against the HF file listing.
REPOS: dict[str, str] = {
    "jackson-core": "fasterxml__jackson-core_dataset.jsonl",
    "jackson-databind": "fasterxml__jackson-databind_dataset.jsonl",
    "jackson-dataformat-xml": "fasterxml__jackson-dataformat-xml_dataset.jsonl",
    "gson": "google__gson_dataset.jsonl",
    "dubbo": "apache__dubbo_dataset.jsonl",
    "jib": "googlecontainertools__jib_dataset.jsonl",
    "mockito": "mockito__mockito_dataset.jsonl",
    "fastjson2": "alibaba__fastjson2_dataset.jsonl",
    "logstash": "elastic__logstash_dataset.jsonl",
}

#: Fields swe_fixtures.py needs. base.sha is checked separately (nested).
_REQUIRED = ("org", "repo", "number", "test_patch", "fix_patch")


def sniff(path: Path) -> str | None:
    """Name what a NON-jsonl file actually is, with the remedy.

    A download can go wrong in ways that all surface as a wall of json errors one per
    line — which says nothing about the cause. Read the first bytes and say it plainly.
    """
    head = path.open("rb").read(400)
    if head[:2] == b"\x1f\x8b":
        return ("the file is GZIP-compressed, not plain jsonl — "
                f"decompress it:  gunzip -c {path} > {path.with_suffix('.jsonl')}")
    if head[:4] == b"PAR1":
        return ("the file is PARQUET, not jsonl — download the .jsonl from "
                "huggingface.co/datasets/ByteDance-Seed/Multi-SWE-bench/tree/main/java")
    low = head[:200].lower()
    if low.lstrip().startswith((b"<!doctype", b"<html", b"<?xml")):
        # Quote the page: "404" and a corporate proxy's "Access Denied" need very
        # different fixes, and the bytes are the only thing that tells them apart.
        text = head.decode("utf-8", "replace")
        m = re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I)
        gist = " ".join((m.group(1) if m else re.sub(r"<[^>]+>", " ", text)).split())[:120]
        return (f"the file is an HTML page, not data — it says: “{gist}”. "
                "A 404 means the upstream name changed; anything about access/proxy/login "
                "means the network intercepted the download.")
    if head.startswith(b"version https://git-lfs"):
        return ("the file is a git-LFS POINTER, not the data — fetch it over https "
                "instead of a git clone:  python3 scripts/swe_fetch.py <repo> --force")
    if b"\x00" in head:
        return ("the file is binary, not jsonl — re-fetch:  "
                "python3 scripts/swe_fetch.py <repo> --force")
    return None


def validate(path: Path) -> tuple[int, str | None]:
    """(record count, error). Rejects the flat HF schema loudly rather than letting
    it become a batch of broken fixtures hours later."""
    n = 0
    if not path.is_file():
        return 0, f"no such file: {path}"
    what = sniff(path)
    if what:
        return 0, what
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if n == 0:
                missing = [k for k in _REQUIRED if not rec.get(k)]
                if not (rec.get("base") or {}).get("sha"):
                    missing.append("base.sha")
                if missing:
                    return 0, (f"not the native Multi-SWE-bench schema — missing "
                               f"{', '.join(missing)}. Keys present: "
                               f"{sorted(rec)[:12]}")
            n += 1
    except json.JSONDecodeError as exc:
        return 0, f"not valid JSONL: {exc}"
    return n, (None if n else "file is empty")


def _download(url: str, dest: Path) -> str | None:
    """Fetch to dest; None on success, else a message. Tries urllib, then curl/wget.

    The fallback is not paranoia: a stock python on macOS ships without a CA bundle
    and fails every https fetch with CERTIFICATE_VERIFY_FAILED, while curl/wget use
    the system trust store and work fine. Falling back keeps one broken interpreter
    from blocking the whole setup.
    """
    try:
        with urllib.request.urlopen(url, timeout=180) as r, dest.open("wb") as f:
            f.write(r.read())
        return None
    except urllib.error.HTTPError as exc:
        return (f"HTTP {exc.code} — the upstream file name may have changed; check "
                "https://huggingface.co/datasets/ByteDance-Seed/Multi-SWE-bench/tree/main/java")
    except Exception as exc:
        first = str(exc)
    for tool, args in (("curl", ["-fsSL", url, "-o", str(dest)]),
                       ("wget", ["-q", url, "-O", str(dest)])):
        if not shutil.which(tool):
            continue
        p = subprocess.run([tool, *args], capture_output=True,
                           encoding="utf-8", errors="replace")
        if p.returncode == 0 and dest.is_file() and dest.stat().st_size:
            print(f"  (urllib failed: {first[:60]}… — fetched with {tool})")
            return None
    return f"download failed: {first}"


def fetch(short: str, out_dir: Path, force: bool) -> bool:
    fname = REPOS[short]
    dest = out_dir / f"{short}.jsonl"
    if dest.is_file() and not force:
        n, err = validate(dest)
        if not err:
            print(f"= {short}: already present ({n} records)")
            return True
        # A cached file that is NOT usable must not block the setup: --force is for
        # replacing a GOOD file, not for escaping a broken one.
        print(f"! {short}: cached file is unusable — {err}")
        print(f"  re-downloading (the bad copy is kept as {dest.name}.bad)")
        dest.replace(dest.with_suffix(dest.suffix + ".bad"))
    url = _HF + fname
    tmp = dest.with_suffix(".part")
    print(f"↓ {short}: {url}")
    err = _download(url, tmp)
    if err:
        print(f"! {short}: {err}")
        tmp.unlink(missing_ok=True)
        return False
    n, err = validate(tmp)
    if err:
        # Keep the bad file out of the way so a later run does not use it.
        tmp.rename(dest.with_suffix(".rejected"))
        print(f"! {short}: {err}  (saved as {dest.with_suffix('.rejected').name})")
        return False
    tmp.rename(dest)
    print(f"+ {short}: {n} instances -> {dest}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repos", nargs="*", help=f"short names: {', '.join(REPOS)}")
    ap.add_argument("--out", type=Path, default=Path.home() / "msb-data")
    ap.add_argument("--all", action="store_true", help="every Java repo")
    ap.add_argument("--list", action="store_true", help="list the known repos and exit")
    ap.add_argument("--force", action="store_true", help="re-download existing files")
    a = ap.parse_args()

    if a.list:
        print("Java repos in Multi-SWE-bench:")
        for k, v in REPOS.items():
            print(f"  {k:24} {v}")
        return 0
    names = list(REPOS) if a.all else a.repos
    if not names:
        ap.print_help()
        return 2
    unknown = [n for n in names if n not in REPOS]
    if unknown:
        print(f"unknown repo(s): {unknown}\nknown: {', '.join(REPOS)}")
        return 2

    a.out.mkdir(parents=True, exist_ok=True)
    ok = [fetch(n, a.out, a.force) for n in names]
    print(f"\n{sum(ok)}/{len(ok)} dataset(s) ready in {a.out}")
    if sum(ok) and len(ok) > 1:
        print(f"Combine them for one sweep:  cat {a.out}/*.jsonl > {a.out}/java-all.jsonl")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
