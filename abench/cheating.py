"""Heuristic cheating/validity detector over an agent run's trace.

Advisory only — flags behaviours that would invalidate a result so a reviewer
can check it: fetching the upstream repo, recovering the original from VCS
history, reading the original off the filesystem outside the run workdir,
filesystem-wide searching, and a final method body near-identical to the
reference. Signals 1–4 are derived from the trace alone (so recompute backfills
past runs); the output-similarity signal is supplied by the caller.
"""
from __future__ import annotations

import re

from .trace_model import StepKind, Trace

_CMD_KEYS = ("command", "cmd", "script")
_PATH_KEYS = ("path", "filePath", "file", "filename")
_URL_KEYS = ("url", "uri")
_QUERY_KEYS = ("query", "q")
_WEB_TOOLS = {"web", "fetch", "webfetch", "websearch", "browser", "browse"}

# 1) network / upstream repo
_NET_CMD = re.compile(
    r"\b(curl|wget|nc|ncat|scp|sftp|ssh)\b|\bgit\s+(clone|fetch|pull|remote|ls-remote)\b",
    re.I)
_URL = re.compile(r"https?://(?!localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])", re.I)
_REPO = re.compile(r"github(usercontent)?\.com|gitlab\.com|bitbucket\.org|sourcegraph", re.I)

# 2) VCS history (recover the original from git)
_VCS = re.compile(
    r"\bgit\s+(log|show|cat-file|reflog|blame|rev-list|format-patch|stash)\b"
    r"|(?:^|[\s\"'=(/])\.git/", re.I)

# 3) reading the original off the FS outside the run workdir. The workdir is a
# temp dir named 'abench-…', so absolute paths under common roots that are NOT
# the workdir and NOT a dependency cache, pointing at SOURCE files, are suspect.
_ABS_PATH = re.compile(r"/(?:tmp|home|root|Users|mnt|opt|srv|workspace|data)/[^\s\"';:|&)]+")
_CACHE = re.compile(
    r"abench-|/\.(gradle|m2|cache|ivy2|cargo|npm|pyenv|sdkman|rustup)/|"
    r"/var/folders/|/private/|node_modules|/jvm/|/jdk", re.I)
_SRCISH = re.compile(r"\.(java|kt|py|go|rs|ts|js|scala|rb|cpp|cc|c|h)(\b|$)|/src/", re.I)

# 4) filesystem-wide search
_SEARCH_TOOL = re.compile(r"\b(find|grep|rg|ag|fd|locate)\b", re.I)
_ROOTISH = re.compile(r"(?:^|\s|=)(/|~|\.\.)(?:/|\s|$)")


def detect_cheating(
    trace: Trace,
    *,
    target_similarity: float | None = None,
    similarity_threshold: float = 0.95,
) -> dict:
    """Return {verdict, signals, target_similarity}. verdict is 'suspicious'
    when any signal fired, else 'clean'. Each signal carries up to 3 short
    evidence snippets."""
    ev: dict[str, list[str]] = {}

    def add(kind: str, snippet: str) -> None:
        bucket = ev.setdefault(kind, [])
        text = " ".join(str(snippet).split())[:140]
        if text and text not in bucket and len(bucket) < 3:
            bucket.append(text)

    for step in trace.steps:
        if step.kind != StepKind.TOOL_CALL:
            continue
        args = step.tool_args or {}
        name = (step.tool_name or "").lower()
        cmd = next((args[k] for k in _CMD_KEYS if isinstance(args.get(k), str)), "")
        path = next((args[k] for k in _PATH_KEYS if isinstance(args.get(k), str)), "")
        url = next((args[k] for k in _URL_KEYS if isinstance(args.get(k), str)), "")
        query = next((args[k] for k in _QUERY_KEYS if isinstance(args.get(k), str)), "")

        if name in _WEB_TOOLS or url or (
            cmd and (_NET_CMD.search(cmd) or _URL.search(cmd) or _REPO.search(cmd))
        ):
            add("network", url or query or cmd or name)

        if cmd and _VCS.search(cmd):
            add("vcs_history", cmd)
        elif path and ".git/" in path:
            add("vcs_history", path)

        for text in (cmd, path):
            if not text:
                continue
            for hit in _ABS_PATH.findall(text):
                if not _CACHE.search(hit) and _SRCISH.search(hit):
                    add("outside_workdir", hit)

        if cmd and _SEARCH_TOOL.search(cmd) and _ROOTISH.search(cmd):
            add("fs_wide_search", cmd)

    signals = [{"type": k, "evidence": v} for k, v in ev.items()]
    if target_similarity is not None and target_similarity >= similarity_threshold:
        signals.append({
            "type": "output_matches_original",
            "evidence": [f"{target_similarity * 100:.0f}% similar to the reference method"],
        })

    return {
        "verdict": "suspicious" if signals else "clean",
        "signals": signals,
        "target_similarity": target_similarity,
    }
